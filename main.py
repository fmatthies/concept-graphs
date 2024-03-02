import logging
import threading

from time import sleep

import flask
from flask import Flask, Response
from flask.logging import default_handler

from main_methods import *
from main_methods import HTTPResponses
from main_utils import ProcessStatus
from preprocessing_util import PreprocessingUtil
from embedding_util import PhraseEmbeddingUtil
from clustering_util import ClusteringUtil
from graph_creation_util import GraphCreationUtil

sys.path.insert(0, "src")
import data_functions
import embedding_functions
import cluster_functions
import util_functions

app = Flask(__name__)
root = logging.getLogger()
root.addHandler(default_handler)

FILE_STORAGE_TMP = "./tmp"

running_processes = {}

f_storage = pathlib.Path(FILE_STORAGE_TMP)
if not f_storage.exists():
    f_storage.mkdir()
populate_running_processes(app, FILE_STORAGE_TMP, running_processes)

# ToDo: file with stopwords will be POSTed: #filter_stop: Optional[list] = None,

# ToDo: I downscale the embeddings twice... (that snuck in somehow); once in SentenceEmbeddings via create(down_scale_algorithm)
# ToDo: and once PhraseCluster via create(down_scale_algorithm). I can't remember why I added this to SentenceEmbeddings later on...
# ToDo: but I should make sure, that there is a check somewhere that the down scaling is not applied twice!

# ToDo: make sure that no arguments can be supplied via config that won't work

# ToDo: endpoints with path arguments should throw a response/warning if there is no saved pickle

# ToDo: get info on each base endpoint, when providing no further args or params (if necessary)

# ToDo: adapt README

# ToDo: the graph draw physics behave weirdly; maybe switch to another (static) rendering


@app.route("/")
def index():
    return jsonify(available_endpoints=['/preprocessing', '/embedding', '/clustering', '/graph',
                                        '/pipeline', '/processes', '/status'])


@app.route("/preprocessing", methods=['GET', 'POST'])
def data_preprocessing():
    app.logger.info("=== Preprocessing started ===")
    if request.method == "POST" and len(request.files) > 0 and "data" in request.files:
        pre_proc = PreprocessingUtil(app, FILE_STORAGE_TMP)

        process_name = read_config(app, pre_proc, StepsName.DATA)

        app.logger.info("Reading labels ...")
        pre_proc.read_labels(request.files.get("labels", None))
        _labels_str = list(pre_proc.labels.values()) if pre_proc.labels is not None else []
        app.logger.info(f"Gathered the following labels:\n\t{_labels_str}")

        app.logger.info("Reading data ...")
        pre_proc.read_data(request.files.get("data", None))
        app.logger.info(f"Counted {len(pre_proc.data)} item ins zip file.")

        app.logger.info(f"Start preprocessing '{process_name}' ...")
        return data_get_statistics(
            pre_proc.start_process(process_name, data_functions.DataProcessingFactory, running_processes)
        )

    elif request.method == "GET":
        jsonify("'/preprocessing' endpoint needs some form of data. Please consult the README/manuals on how to provide it.")

    elif len(request.files) <= 0 or "data" not in request.files:
        app.logger.error("There were no files at all or no data files POSTed."
                         " At least a zip folder with the text data is necessary!\n"
                         " It is also necessary to conform to the naming convention!\n"
                         "\t\ti.e.: curl -X POST -F data=@\"#SOME/PATH/TO/FILE.zip\"")
    return jsonify("Nothing to do.")


@app.route("/preprocessing/<path_arg>", methods=['GET'])
def data_preprocessing_with_arg(path_arg):
    process = request.args.get("process", "default")
    path_arg = path_arg.lower()

    _path_args = ["statistics", "noun_chunks"]
    if path_arg in _path_args:
        data_obj = data_functions.DataProcessingFactory.load(
            pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(process) / f"{process}_data.pickle"))
    else:
        return jsonify(error=f"No such path argument '{path_arg}' for 'preprocessing' endpoint.",
                       possible_path_args=[f"/{p}" for p in _path_args])

    if path_arg == "statistics":
        return data_get_statistics(data_obj)
    elif path_arg == "noun_chunks":
        return jsonify(
            noun_chunks=data_obj.data_chunk_sets
        )


@app.route("/embedding", methods=['POST', 'GET'])
def phrase_embedding():
    app.logger.info("=== Phrase embedding started ===")
    if request.method in ["POST", "GET"]:
        phra_emb = PhraseEmbeddingUtil(app, FILE_STORAGE_TMP)

        process_name = read_config(app, phra_emb, StepsName.EMBEDDING)

        app.logger.info(f"Start phrase embedding '{process_name}' ...")
        try:
            return embedding_get_statistics(
                phra_emb.start_process(process_name, embedding_functions.SentenceEmbeddingsFactory, running_processes)
            )
        except FileNotFoundError:
            return jsonify(f"There is no processed data for the '{process_name}' process to be embedded.")
    return jsonify("Nothing to do.")


@app.route("/embedding/<path_arg>", methods=['GET'])
def phrase_embedding_with_arg(path_arg):
    process = request.args.get("process", "default")
    path_arg = path_arg.lower()

    _path_args = ["statistics"]
    if path_arg in _path_args:
        emb_obj = embedding_functions.SentenceEmbeddingsFactory.load(
            pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(process) / f"{process}_data.pickle"),
            pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(process) / f"{process}_embedding.pickle"),
        )
    else:
        return jsonify(error=f"No such path argument '{path_arg}' for 'embedding' endpoint.",
                       possible_path_args=[f"/{p}" for p in _path_args])

    if path_arg == "statistics":
        return embedding_get_statistics(emb_obj)


@app.route("/clustering", methods=['POST', 'GET'])
def phrase_clustering():
    app.logger.info("=== Phrase clustering started ===")
    if request.method in ["POST", "GET"]:
        saved_config = request.args.get("config", False)
        if not saved_config:
            phra_clus = ClusteringUtil(app, FILE_STORAGE_TMP)

            process_name = read_config(app, phra_clus, StepsName.CLUSTERING)

            app.logger.info(f"Start phrase clustering '{process_name}' ...")
            try:
                _cluster_gen = phra_clus.start_process(
                    process_name, cluster_functions.PhraseClusterFactory, running_processes
                )
                return clustering_get_concepts(_cluster_gen)
            except FileNotFoundError:
                return jsonify(f"There is no embedded data for the '{process_name}' process to be clustered.")
        else:
            return jsonify(saved_config)
    return jsonify("Nothing to do.")


@app.route("/clustering/<path_arg>", methods=['GET'])
def clustering_with_arg(path_arg):
    process = request.args.get("process", "default")
    top_k = int(request.args.get("top_k", 15))
    distance = float(request.args.get("distance", .6))
    path_arg = path_arg.lower()

    _path_args = ["concepts"]
    if path_arg in _path_args:
        cluster_obj = cluster_functions.PhraseClusterFactory.load(
            pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(process) / f"{process}_clustering.pickle"),
        )
    else:
        return jsonify(error=f"No such path argument '{path_arg}' for 'clustering' endpoint.",
                       possible_path_args=[f"/{p}" for p in _path_args])

    if path_arg == "concepts":
        emb_obj = util_functions.load_pickle(
            pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / f"{process}_embedding.pickle"))
        _cluster_gen = embedding_functions.show_top_k_for_concepts(
            cluster_obj=cluster_obj.concept_cluster, embedding_object=emb_obj, yield_concepts=True,
            top_k=top_k, distance=distance
        )
        return clustering_get_concepts(_cluster_gen)


@app.route("/graph", methods=['GET'])
def graph_base_endpoint():
    return jsonify(
        path_parameter=[
            {
                "statistics": {
                     "query_parameters": [
                         get_query_param_help_text("process"),
                     ]
                }
            },
            {
                "creation": {
                    "query_parameters": [
                        get_query_param_help_text("process"),
                        get_query_param_help_text("exclusion_ids")
                    ]
                }
            },
            {
                "#GRAPH_ID": {
                    "query_parameters": [
                        get_query_param_help_text("process"),
                        get_query_param_help_text("draw")
                    ]
                }
            },
        ],
    ), HTTPResponses.NOT_FOUND


@app.route("/graph/<path_arg>", methods=['POST', 'GET'])
def graph_creation_with_arg(path_arg):
    process = request.args.get("process", "default")
    draw = get_bool_expression(request.args.get("draw", False))
    path_arg = path_arg.lower()

    _path_args = ["statistics", "creation"]
    if path_arg in _path_args:
        try:
            if path_arg == "statistics":
                return graph_get_statistics(app, process, FILE_STORAGE_TMP)
            elif path_arg == "creation":
                return graph_create(app, FILE_STORAGE_TMP)
        except FileNotFoundError:
            return Response(f"There is no graph data present for '{process}'.\n",
                            status=int(HTTPResponses.NOT_FOUND))
    elif path_arg.isdigit():
        graph_nr = int(path_arg)
        return graph_get_specific(process, graph_nr, path=FILE_STORAGE_TMP, draw=draw)
    else:
        return Response(
            f"No such path argument '{path_arg}' for 'graph' endpoint.\n"
            f"Possible path arguments are: {', '.join([p for p in _path_args] + ['#ANY_INTEGER'])}\n",
            status=int(HTTPResponses.BAD_REQUEST))


@app.route("/pipeline", methods=['POST'])
def complete_pipeline():
    data = request.files.get("data", False)
    document_server_config = request.files.get("document_server_config", False)
    replace_keys = None

    query_params = get_pipeline_query_params(app, request, running_processes)
    if isinstance(query_params, tuple) and isinstance(query_params[0], flask.Response):
        return query_params

    # ToDo
    content_type = request.headers.get("Content-Type")
    if content_type == "application/json":
        config_object = parse_config_json(request.json)

    if not data and not document_server_config:
        return jsonify(
            name=query_params.process_name,
            status="Neither data provided for upload with 'data' key nor a config file for documents on a server"
        ), int(HTTPResponses.BAD_REQUEST)
    elif data and not document_server_config:
        _tmp_data = pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(".tmp_streams") / data.filename)
        _tmp_data.parent.mkdir(parents=True, exist_ok=True)
        data.save(_tmp_data)
        data = _tmp_data
    else:
        base_config = get_data_server_config(document_server_config, app)
        if not check_data_server(url=base_config["url"], port=base_config["port"], index=base_config["index"]):
            return jsonify(
                name=query_params.process_name,
                status=f"There is no data server at the specified location ({base_config}) or it contains no data."
            ), int(HTTPResponses.NOT_FOUND)
        data = get_documents_from_es_server(
            url=base_config['url'], port=base_config['port'], index=base_config['index'], size=int(base_config['size'])
        )
        replace_keys = base_config.get("replace_keys", {"text": "content"})

    labels = request.files.get("labels", None)
    if labels is not None:
        _tmp_labels = pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(".tmp_streams") / labels.filename)
        _tmp_labels.parent.mkdir(parents=True, exist_ok=True)
        labels.save(_tmp_labels)
        labels = _tmp_labels

    processes = [
        (StepsName.DATA, PreprocessingUtil, request.files.get(f"{StepsName.DATA}_config", None),
         data_functions.DataProcessingFactory,),
        (StepsName.EMBEDDING, PhraseEmbeddingUtil, request.files.get(f"{StepsName.EMBEDDING}_config", None),
         embedding_functions.SentenceEmbeddingsFactory,),
        (StepsName.CLUSTERING, ClusteringUtil, request.files.get(f"{StepsName.CLUSTERING}_config", None),
         cluster_functions.PhraseClusterFactory,),
        (StepsName.GRAPH, GraphCreationUtil, request.files.get(f"{StepsName.GRAPH}_config", None),
         cluster_functions.WordEmbeddingClustering,)
    ]
    processes_threading = []
    running_processes[query_params.process_name] = {"status": {}, "name": query_params.process_name}

    for _name, _proc, _conf, _fact in processes:
        process_obj = _proc(app=app, file_storage=FILE_STORAGE_TMP)
        running_processes[query_params.process_name]["status"][_name] = ProcessStatus.STARTED
        if process_obj.has_pickle(query_params.process_name):
            if _name in query_params.omitted_pipeline_steps or query_params.skip_present:
                logging.info(f"Skipping {_name} because "
                             f"{'omitted' if _name in query_params.omitted_pipeline_steps else 'skip_present'}.")
                running_processes[query_params.process_name]["status"][_name] = ProcessStatus.FINISHED
                continue
            else:
                process_obj.delete_pickle(query_params.process_name)
        read_config(app=app, processor=process_obj, process_type=_name,
                    process_name=query_params.process_name, config=_conf, language=query_params.language)
        if _name == StepsName.DATA:
            process_obj.read_labels(labels)
            process_obj.read_data(data, replace_keys=replace_keys)
        processes_threading.append((process_obj, _fact, _name, ))

    pipeline_thread = threading.Thread(group=None, target=start_processes, name=None,
                                       args=(app, processes_threading, query_params.process_name, running_processes, ))
    pipeline_thread.start()
    sleep(1)

    if query_params.return_statistics:
        pipeline_thread.join()
        _graph_stats_dict = graph_get_statistics(app=app, data=query_params.process_name, path=FILE_STORAGE_TMP)
        return (
            jsonify(name=query_params.process_name, **_graph_stats_dict),
            int(HTTPResponses.OK) if "error" not in _graph_stats_dict else int(HTTPResponses.INTERNAL_SERVER_ERROR)
        )
    else:
        return (
            jsonify(name=query_params.process_name, status=running_processes.get(query_params.process_name, {"status": {}}).get("status")),
            int(HTTPResponses.ACCEPTED)
        )


@app.route("/processes", methods=['GET'])
def get_all_processes_api():
    _process_detailed = get_all_processes(FILE_STORAGE_TMP)
    if len(_process_detailed) > 0:
        return jsonify(processes=_process_detailed)
    else:
        return Response("No saved processes.", int(HTTPResponses.NOT_FOUND))


@app.route("/status", methods=['GET'])
def get_status_of():
    _process = request.args.get("process", "default")
    if _process is not None:
        _response = running_processes.get(_process, None)
        if _response is not None:
            return jsonify(_response), int(HTTPResponses.OK)
    return jsonify(f"No such (running) process: '{_process}'"), int(HTTPResponses.NOT_FOUND)


@app.route("/status/document-server", methods=['POST', 'GET'])
def get_data_server():
    # if request.method == "GET" and request.args.get("port", False):
    #
    #     return jsonify()
    if request.method == "POST":
        document_server_config = request.files.get("document_server_config", False)
        if not document_server_config:
            return jsonify(
                name="document server check",
                status=f"No document server config file provided"), int(HTTPResponses.BAD_REQUEST)
        base_config = get_data_server_config(document_server_config, app)
        if not check_data_server(url=base_config["url"], port=base_config["port"], index=base_config["index"]):
            return jsonify(f"There is no data server at the specified location ({base_config}) or it contains no data."), int(
                HTTPResponses.NOT_FOUND)
        return jsonify(f"Data server reachable under: '{base_config['url']}:{base_config['port']}/{base_config['index']}'"), int(
            HTTPResponses.OK)


if __name__ in ["__main__"]:
    app.run(host="0.0.0.0", port=9010)
