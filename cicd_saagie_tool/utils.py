import logging

from saagieapi import SaagieApi, GraphPipeline, ConditionStatusNode, ConditionExpressionNode
import json
import shutil
import os
import yaml
from pathlib import Path
import re
import unicodedata
import uuid


def fix_forbidden_alias(alias):
    forbidden_alias = "INIT"
    return f"ALIAS_{forbidden_alias}" if alias.lower() == forbidden_alias.lower() else alias


def normalize_name_to_alias(name, default_alias):
    alias = unicodedata.normalize('NFD', name)
    alias = re.sub(r'[^\x00-\x7F]+', '', alias)
    alias = re.sub(r'[ -]', '_', alias)
    alias = re.sub(r'[^A-Za-z0-9_]', '', alias)
    alias = default_alias if len(alias) < 2 else alias
    return fix_forbidden_alias(alias)


def handle_log_error(msg, exception):
    logging.warning(msg)
    logging.error("Something went wrong %s", exception)
    raise exception


def package_code(name_file, root_dir, archive_format="zip"):
    """
    Create a zip archive of a directory
    :param name_file: string, name of the file to create, including the path, minus any format-specific extension
    :param root_dir: string, a directory that will be the root directory of the archive
    :param archive_format: string, archive format, can be "zip", "tar", "gztar", "bztar" or "bztar"
    :return: string, name of the archive
    """
    if root_dir:
        logging.info(f"Creating archive: {name_file}.{archive_format} ...")
        return shutil.make_archive(name_file, archive_format, root_dir)
    else:
        return None


def connect_to_saagie(url, id_platform, user, password, realm):
    """
    Create an instance of SaagieAPI in order to interact with Saagie
    :param url: string, Saagie URL
    :param id_platform: string, Saagie ID platform
    :param user: string, Saagie's user
    :param password: string, Saagie user's password
    :param realm: string, Saagie realm
    :return: instance of SaagieAPI
    """
    logging.debug(f"Connecting to Saagie ...")
    saagie_client = SaagieApi(url_saagie=url,
                              id_platform=id_platform,
                              user=user,
                              password=password,
                              realm=realm)

    return saagie_client


def create_or_upgrade_job(client_saagie, job_config_file, env_config_file):
    """
    Package code and then create or upgrade a job on Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAPI
    :param job_config_file: str, job config file path
    :param env_config_file: str, path of environment config file
    :return: dict, dict of job informaiton
    """
    try:
        logging.debug(f"Loading job config file: [{job_config_file}] ...")
        with open(job_config_file, "r", encoding="utf8") as f:
            job_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading job config file: [{job_config_file}]", e)
    try:
        logging.debug(f"Loading env config file: [{env_config_file}] ...")
        with open(env_config_file, "r", encoding="utf8") as f:
            env_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading env config file: [{env_config_file}]", e)

    release_note = "WIP"
    url_git = ""
    if "CI" in os.environ:
        if "GITHUB_SERVER_URL" in os.environ:
            url_git = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/commit/{os.environ['GITHUB_SHA']}"
            release_note = f"{os.environ['CI_COMMIT_MESSAGE']} - {url_git}"
        else:
            url_git = f"{os.environ['CI_PROJECT_URL']}/-/commit/{os.environ['CI_COMMIT_SHA']}"
            release_note = f"{os.environ['CI_COMMIT_MESSAGE']}"

    res = client_saagie.jobs.create_or_upgrade(
        job_name=job_config["job_name"],
        project_id=env_config["project_id"],
        file=job_config["file_path"] if "file_path" in job_config and bool(job_config["file_path"]) else None,
        use_previous_artifact=False,
        description=job_config["description"] if "description" in job_config else None,
        category=job_config["category"] if "category" in job_config else None,
        technology=job_config["technology"] if "technology" in job_config else None,
        technology_catalog=job_config["technology_catalog"] if "technology_catalog" in job_config else None,
        runtime_version=job_config["runtime_version"] if "runtime_version" in job_config and bool(job_config["runtime_version"]) else None,
        command_line=job_config["command_line"] if "command_line" in job_config and bool(job_config["command_line"]) else None,
        release_note=release_note,
        extra_technology=job_config["extra_technology"] if "extra_technology" in job_config and bool(job_config["extra_technology"]) else None,
        extra_technology_version=job_config["extra_technology_version"] if "extra_technology_version" in job_config and bool(job_config["extra_technology_version"]) else None,
        source_url=url_git,
        docker_info=job_config["docker_info"] if "docker_info" in job_config and bool(job_config["docker_info"]) else None,
    )
    return res


def run_job(client_saagie, job_config_file, env_config_file):
    """
    Run a job on Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAP
    :param job_config_file: str, job config file path
    :param env_config_file: str, path of environment config file
    :return: dict, dict of job instance ID and status
    """
    try:
        logging.debug(f"Loading job config file: [{job_config_file}] ...")
        with open(job_config_file, "r") as f:
            job_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading job config file: [{job_config_file}]", e)
    try:
        logging.debug(f"Loading env config file: [{env_config_file}] ...")
        with open(env_config_file, "r") as f:
            env_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading env config file: [{env_config_file}]", e)
    logging.debug(f"Getting job ID: [{job_config['job_name']}] ...")
    job_id = client_saagie.jobs.get_id(job_config["job_name"], env_config["project_name"])
    logging.info("Job ID: " + job_id)
    logging.debug(f"Running job: [{job_id}] ...")
    return client_saagie.jobs.run(job_id)


def create_graph(saagie_client, pipeline_config_file, project_id):
    """
    Create the Graph of Saagie graph pipeline
    :param saagie_client: SaagieAPI, an instance of SaagieAPI
    :param pipeline_config_file: str, pipeline config file path
    :param project_id: str, Project ID of Saagie
    :return: saagieapi.GraphPipeline
    """
    file_extension = Path(pipeline_config_file).suffix
    logging.debug(f"Loading pipeline config file: [{pipeline_config_file}] ...")
    if file_extension == ".json":
        with open(pipeline_config_file, "r", encoding="utf8") as f:
            pipeline_config = json.load(f)
    elif file_extension == ".yaml" or file_extension == ".yml":
        with open(pipeline_config_file, "r", encoding="utf8") as f:
            pipeline_config = yaml.safe_load(f)
    else:
        raise Exception("Pipeline artefact file must be a json or yaml file")

    pipeline_info = pipeline_config["pipeline"]
    graph_pipeline = GraphPipeline()
    list_job_nodes = []
    list_condition_nodes = []
    dict_ids = {}

    logging.debug("Creating graph pipeline ...")
    logging.debug("Creating job nodes ...")
    # Find all job nodes
    for i in range(len(pipeline_info["nodes"])):
        if "job" in pipeline_info["nodes"][i].keys():
            job_node_info = pipeline_info["nodes"][i]["job"]
            job_id = saagie_client.jobs.get_info_by_alias(project_id=project_id,
                                                          job_alias=job_node_info["alias"],
                                                          instances_limit=1,
                                                          versions_only_current=True)["jobByAlias"]["id"]
            dict_ids = create_dict_uuid_id(dict_ids, job_node_info)

            node_dict = {
                "id": dict_ids[job_node_info["node"]],
                "job": {"id": job_id},
                "nextNodes": [dict_ids[next_node] for next_node in job_node_info["nextNodes"]],
            }
            list_job_nodes.append(node_dict)

        elif "conditionExpression" in pipeline_info["nodes"][i].keys():
            condition_node_info = pipeline_info["nodes"][i]["conditionExpression"]

            dict_ids = create_dict_uuid_id(dict_ids, condition_node_info)

            condition_dict = {
                "id": dict_ids[condition_node_info["node"]],
                "nextNodesSuccess": [dict_ids[next_node] for next_node in condition_node_info["nextNodesSuccess"]],
                "nextNodesFailure": [dict_ids[next_node] for next_node in condition_node_info["nextNodesFailure"]],
                "condition": {"custom": {"expression": condition_node_info["expression"]}}
            }
            list_condition_nodes.append(condition_dict)

        elif "conditionStatus" in pipeline_info["nodes"][i].keys():
            condition_node_info = pipeline_info["nodes"][i]["conditionStatus"]
            dict_ids = create_dict_uuid_id(dict_ids, condition_node_info)

            condition_dict = {
                "id": dict_ids[condition_node_info["node"]],
                "nextNodesSuccess": [dict_ids[next_node] for next_node in condition_node_info["nextNodesSuccess"]],
                "nextNodesFailure": [dict_ids[next_node] for next_node in condition_node_info["nextNodesFailure"]],
                "condition": {"status": {"value": condition_node_info["trigger"]}}
            }
            list_condition_nodes.append(condition_dict)
        else:
            logging.warning(f"{pipeline_info['nodes'][i]} not recognizing .... Some error in your pipeline config file")
    logging.debug(f"List of job nodes: {list_job_nodes}")
    logging.debug(f"List of condition nodes: {list_condition_nodes}")
    graph_pipeline.list_job_nodes = list_job_nodes
    graph_pipeline.list_conditions_nodes = list_condition_nodes
    return graph_pipeline


def create_or_upgrade_graph_pipeline(client_saagie, pipeline_config_file, env_config_file):
    """
    Create or upgrade pipeline in Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAPI
    :param pipeline_config_file: str, pipeline config file path
    :param env_config_file: str, path of environment config file
    :return: dict of pipeline information
    """
    try:
        with open(pipeline_config_file, "r", encoding="utf8") as f:
            pipeline_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading pipeline config file: [{pipeline_config_file}]", e)

    file_extension = Path(pipeline_config["file_path"]).suffix
    if file_extension == ".json":
        with open(pipeline_config["file_path"], "r", encoding="utf8") as f:
            pipeline_info_schema = json.load(f)
    elif file_extension == ".yaml" or file_extension == ".yml":
        with open(pipeline_config["file_path"], "r", encoding="utf8") as f:
            pipeline_info_schema = yaml.safe_load(f)
    else:
        raise Exception("Pipeline artefact file must be json or yaml file")
    with open(env_config_file, "r") as f:
        env_config = json.load(f)

    pipeline_info = pipeline_info_schema["pipeline"]
    graph_pipeline = create_graph(client_saagie, pipeline_config["file_path"], env_config["project_id"])
    release_note = "WIP"
    url_git = ""
    if "CI" in os.environ:
        if "GITHUB_SERVER_URL" in os.environ:
            url_git = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/commit/{os.environ['GITHUB_SHA']}"
            release_note = f"{os.environ['CI_COMMIT_MESSAGE']} - {url_git}"
        else:
            url_git = f"{os.environ['CI_PROJECT_URL']}/-/commit/{os.environ['CI_COMMIT_SHA']}"
            release_note = f"{os.environ['CI_COMMIT_MESSAGE']}"

    alias = pipeline_info["alias"] if "alias" in pipeline_info and bool(pipeline_info["alias"]) else normalize_name_to_alias(pipeline_info["name"], pipeline_info["alias"])

    res = client_saagie.pipelines.create_or_upgrade(
        name=pipeline_info["name"],
        alias=alias,
        project_id=env_config["project_id"],
        graph_pipeline=graph_pipeline,
        release_note=release_note,
        description=pipeline_info["description"] if "description" in pipeline_info and bool(pipeline_info["description"]) else None,
        has_execution_variables_enabled=pipeline_info["executionVariables"] if
        "executionVariables" in pipeline_info and bool(pipeline_info["executionVariables"]) else None,
        source_url=url_git
    )
    return res


def run_pipeline(client_saagie, pipeline_config_file, env_config_file):
    """
    Run a pipeline on Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAP
    :param pipeline_config_file: str, pipeline config file path
    :param env_config_file: str, Path of environment config file
    :return: dict, dict of job instance ID and status
    """
    try:
        with open(pipeline_config_file, "r") as f:
            pipeline_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading pipeline config file: [{pipeline_config_file}]", e)

    file_extension = Path(pipeline_config["file_path"]).suffix
    if file_extension == ".json":
        with open(pipeline_config["file_path"], "r") as f:
            pipeline_info = json.load(f)
    elif file_extension == ".yaml" or file_extension == ".yml":
        with open(pipeline_config["file_path"], "r") as f:
            pipeline_info = yaml.safe_load(f)
    else:
        raise Exception("Pipeline config file must be json or yaml file")

    logging.debug(f"Loading environment config file: {env_config_file} ...")
    with open(env_config_file, "r") as f:
        env_config = json.load(f)
    logging.debug(f"Getting pipeline ID of {pipeline_info['pipeline_name']} ...")
    pipeline_id = client_saagie.pipelines.get_id(project_name=env_config["project_name"], pipeline_name=pipeline_info["pipeline_name"])
    logging.info("Pipeline ID: " + pipeline_id)
    logging.debug(f"Running pipeline: [{pipeline_id}]...")
    return client_saagie.pipelines.run(pipeline_id)


def create_dict_uuid_id(dict_ids, node):
    """
    Create a dictionary of node id and uuid
    :param dict_ids: dict, dictionary of node id and uuid
    :param node: dict, node information
    :return:
    """
    result_dict = dict_ids
    if node["node"] not in result_dict.keys():
        result_dict[node["node"]] = str(uuid.uuid4())
    if "nextNodes" in node.keys():
        for next_node in node["nextNodes"]:
            if next_node not in result_dict.keys():
                result_dict[next_node] = str(uuid.uuid4())
    if "nextNodesSuccess" in node.keys():
        for next_node in node["nextNodesSuccess"]:
            if next_node not in result_dict.keys():
                dict_ids[next_node] = str(uuid.uuid4())
    if "nextNodesFailure" in node.keys():
        for next_node in node["nextNodesSuccess"]:
            if next_node not in result_dict.keys():
                dict_ids[next_node] = str(uuid.uuid4())
    return result_dict
