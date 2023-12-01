import logging
import threading

from enum import IntEnum
from time import sleep

from flask import Flask, Response
from flask.logging import default_handler

from main_methods import *
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

FILE_STORAGE_TMP = "./tmp"  # ToDo: replace it with proper path in docker

steps_relation_dict = {
    "data": 1,
    "embedding": 2,
    "clustering": 3,
    "graph": 4
}

running_processes = {}

# ToDo: file with stopwords will be POSTed: #filter_stop: Optional[list] = None,

# ToDo: I downscale the embeddings twice... (that snuck in somehow); once in SentenceEmbeddings via create(down_scale_algorithm)
# ToDo: and once PhraseCluster via create(down_scale_algorithm). I can't remember why I added this to SentenceEmbeddings later on...
# ToDo: but I should make sure, that there is a check somewhere that the down scaling is not applied twice!

# ToDo: make sure that no arguments can be supplied via config that won't work

# ToDo: endpoints with path arguments should throw a response/warning if there is no saved pickle

# ToDo: get info on each base endpoint, when providing no further args or params (if necessary)

# ToDo: adapt README

# ToDo: when starting the server, read all processes and fill 'running_processes' accordingly


class HTTPResponses(IntEnum):
    OK = 200
    ACCEPTED = 202
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    INTERNAL_SERVER_ERROR = 500
    NOT_IMPLEMENTED = 501
    SERVICE_UNAVAILABLE = 503


@app.route("/")
def index():
    return jsonify(available_endpoints=['/preprocessing', '/embedding', '/clustering', '/graph',
                                        '/pipeline', '/processes', '/status'])


@app.route("/preprocessing", methods=['GET', 'POST'])
def data_preprocessing():
    app.logger.info("=== Preprocessing started ===")
    if request.method == "POST" and len(request.files) > 0 and "data" in request.files:
        pre_proc = PreprocessingUtil(app, FILE_STORAGE_TMP)

        process_name = read_config(app, pre_proc, "data")

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
        pass

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

        process_name = read_config(app, phra_emb, "embedding")

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

            process_name = read_config(app, phra_clus, "clustering")

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


@app.route("/graph/<path_arg>", methods=['POST', 'GET'])
def graph_creation_with_arg(path_arg):
    process = request.args.get("process", "default")
    draw = True if request.args.get("draw", "false").lower() == "true" else False
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
    corpus = request.args.get("process", "default")

    app.logger.info(f"Using process name '{corpus}'")
    language = {"en": "en", "de": "de"}.get(request.args.get("lang", "en"), "en")
    app.logger.info(f"Using preset language settings for '{language}'")

    skip_present = request.args.get("skip_present", True)
    if isinstance(skip_present, str):
        skip_present = get_bool_expression(skip_present, True)
    if skip_present:
        app.logger.info("Skipping present saved steps")

    return_statistics = request.args.get("return_statistics", False)
    if isinstance(return_statistics, str):
        return_statistics = get_bool_expression(return_statistics, True)

    data = request.files.get("data", False)
    if not data:
        return jsonify("No data provided with 'data' key")
    else:
        _tmp_data = pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(".tmp_streams") / data.filename)
        _tmp_data.parent.mkdir(parents=True, exist_ok=True)
        data.save(_tmp_data)
        data = _tmp_data

    labels = request.files.get("labels", None)
    if labels is not None:
        _tmp_labels = pathlib.Path(pathlib.Path(FILE_STORAGE_TMP) / pathlib.Path(".tmp_streams") / labels.filename)
        _tmp_labels.parent.mkdir(parents=True, exist_ok=True)
        labels.save(_tmp_labels)
        labels = _tmp_labels

    processes = [
        ("data", PreprocessingUtil, request.files.get("data_config", None),
         data_functions.DataProcessingFactory,),
        ("embedding", PhraseEmbeddingUtil, request.files.get("embedding_config", None),
         embedding_functions.SentenceEmbeddingsFactory,),
        ("clustering", ClusteringUtil, request.files.get("clustering_config", None),
         cluster_functions.PhraseClusterFactory,),
        ("graph", GraphCreationUtil, request.files.get("graph_config", None),
         cluster_functions.WordEmbeddingClustering,)
    ]
    processes_threading = []
    running_processes[corpus] = {"status": {}}

    for _name, _proc, _conf, _fact in processes:
        process_obj = _proc(app=app, file_storage=FILE_STORAGE_TMP)
        running_processes[corpus]["status"][_name] = ProcessStatus.STARTED
        if process_obj.has_pickle(corpus):
            if skip_present:
                running_processes[corpus]["status"][_name] = ProcessStatus.FINISHED
                continue
            else:
                process_obj.delete_pickle(corpus)
        read_config(app=app, processor=process_obj, process_type=_name,
                    process_name=corpus, config=_conf, language=language)
        if _name == "data":
            process_obj.read_labels(labels)
            process_obj.read_data(data)
        processes_threading.append((process_obj, _fact, ))

    pipeline_thread = threading.Thread(group=None, target=start_processes, name=None,
                                       args=(processes_threading, corpus, running_processes, ))
    pipeline_thread.start()
    sleep(1)

    if return_statistics:
        return graph_get_statistics(app, corpus, FILE_STORAGE_TMP)
    else:
        return jsonify(name=corpus), int(HTTPResponses.ACCEPTED)


@app.route("/processes", methods=['GET'])
def get_all_processes_api():
    _process_detailed = get_all_processes(FILE_STORAGE_TMP, steps_relation_dict)
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
            return jsonify(_response, int(HTTPResponses.OK))
    return jsonify(f"No such (running) process: '{_process}'"), int(HTTPResponses.NOT_FOUND)


if __name__ == "__main__":
    f_storage = pathlib.Path(FILE_STORAGE_TMP)
    if not f_storage.exists():
        f_storage.mkdir()
    app.run()
