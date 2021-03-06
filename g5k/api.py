from api.tool import safe_string, decrypt_password
from database.connector import open_session, close_session
from database.tables import Action, ActionProperty, Schedule
from datetime import datetime, timedelta, timezone
from grid5000 import Grid5000
from importlib import import_module
from lib.config_loader import get_config
from agent_exec import free_reserved_node, new_action, init_action_process, save_reboot_state
import json, logging, os, pytz, requests, time


# The required properties to configure the g5k nodes from the configure panel
CONFIGURE_PROP = {
    "form_ssh_key": { "values": [], "mandatory": False }
}


def g5k_connect(args):
    return Grid5000(
        username = args["g5k_user"],
        password = decrypt_password(args["g5k_password"])
    ).sites[get_config()["g5k_site"]]


# Delete the jobs existing in the schedule but not in the g5k API
def check_deleted_jobs(db_jobs, g5k_jobs, db):
    """
    db_jobs: { job_uid: db_schedule_obj }
    g5k_jobs: the return of g5k_site.jobs.list()
    """
    to_delete = []
    for job in db_jobs:
        found = False
        for g in g5k_jobs:
            if str(g.uid) == job:
                found = True
        if not found:
            to_delete.append(db_jobs[job])
    for job in to_delete:
        logging.warning("[%s] is deleted because it does not exist in g5k" % job.node_name)
        delete_job(job, db)


def delete_job(db_job, db):
    # Delete the actions associated to this job
    for a in db.query(Action).filter(Action.node_name == db_job.node_name).all():
        db.delete(a)
    # Delete the action properties associated to this job
    for a in db.query(ActionProperty).filter(ActionProperty.node_name == db_job.node_name).all():
        db.delete(a)
    # Delete the job from the Schedule table
    db.delete(db_job)


def build_server_list(g5k_site):
    # The file to build the server list without querying the grid5000 API
    server_file = "node-g5k.json"
    # Get all nodes in the default queue of this site
    servers = {}
    if os.path.isfile(server_file):
        with open(server_file, "r") as f:
            servers = json.load(f)
    else:
        # List all nodes of the site
        logging.info("Query the API to build the server list")
        for cl in g5k_site.clusters.list():
            for node in g5k_site.clusters[cl.uid].nodes.list():
                if "default" in node.supported_job_types["queues"]:
                    servers[node.uid] = {
                        "name": node.uid,
                        "site": g5k_site.uid,
                        "cluster": cl.uid,
                        "cpu_nb": str(node.architecture["nb_threads"]),
                        "memoryMB": str(node.main_memory["ram_size"] / 1024 / 1024 / 1024),
                        "model": node.chassis["name"]
                    }
        # Remove dead servers
        nodes = g5k_site.status.list().nodes
        for node  in nodes:
            node_name = node.split(".")[0]
            if node_name in servers:
                if nodes[node]["hard"] == "dead":
                    del servers[node_name]
        with open(server_file, "w") as f:
            f.write(json.dumps(servers, indent = 4))
    return servers


# Convert a list of grid5000 status to a list of reservations
# Parameter: *.status.list().nodes
def status_to_reservations(node_status):
    result = {}
    for node in node_status:
        if len(node_status[node]["reservations"]) > 0:
            node_name = node.split(".")[0]
            result[node_name] = []
            for resa in node_status[node]["reservations"]:
                start_date = resa["scheduled_at"]
                end_date = start_date + resa["walltime"]
                result[node_name].append({
                    "owner": resa["user_uid"],
                    "start_date": start_date,
                    "end_date": end_date
                })
    return result


def client_list(arg_dict):
    return json.dumps({ "error": "DHCP client list is not available from g5k agents" })


def environment_list(arg_dict):
    return json.dumps({ "error": "Environment list is not available from g5k agents" })


def node_bootfiles(arg_dict):
    return json.dumps({
        "error": "Upload boot files is not available for g5k agents."
    })


def node_configure(arg_dict):
    if "user" not in arg_dict or "@" not in arg_dict["user"]:
        return json.dumps({
            "parameters": {
                "user": "email@is.fr"
            }
        })
    result = {}
    # The list of the g5k environments
    env_names = [
        "centos7-x64-min",
        "centos8-x64-min",
        "debian10-x64-base",
        "debian10-x64-big",
        "debian10-x64-min",
        "debian10-x64-nfs",
        "debian10-x64-std",
        "debian10-x64-xen",
        "debian9-x64-base",
        "debian9-x64-big",
        "debian9-x64-min",
        "debian9-x64-nfs",
        "debian9-x64-std",
        "debian9-x64-xen",
        "debiantesting-x64-min",
        "ubuntu1804-x64-min",
        "ubuntu2004-x64-min"
    ]
    # Common properties to every kind of nodes
    conf_prop = {
        "node_bin": { "values": [], "mandatory": True },
        "environment": { "values": env_names, "mandatory": True }
    }
    conf_prop.update(CONFIGURE_PROP)
    # Get the jobs in the schedule by reading the DB
    db = open_session()
    schedule = db.query(Schedule).filter(Schedule.owner == arg_dict["user"]).all()
    uids = { sch.node_name: sch for sch in schedule}
    # Connect to the grid5000 API
    g5k_site = g5k_connect(arg_dict)
    # Get the grid5000 jobs for the grid5000 user
    user_jobs = g5k_site.jobs.list(state = "running", user = arg_dict["g5k_user"])
    user_jobs += g5k_site.jobs.list(state = "waiting", user = arg_dict["g5k_user"])
    # Deleted jobs that do not exist anymore
    check_deleted_jobs(uids, user_jobs, db)
    # Add the unregistered grid5000 jobs to the DB
    for j in user_jobs:
        # Wait for the start_date
        while j.started_at == 0:
            j.refresh()
            time.sleep(1)
        job_id = str(j.uid)
        if job_id in uids:
            schedule = uids[job_id]
        else:
            start_date = j.started_at
            end_date = j.started_at + j.walltime
            # Record the job properties to the database
            schedule = Schedule()
            schedule.node_name = str(j.uid)
            schedule.owner = arg_dict["user"]
            schedule.start_date = start_date
            schedule.end_date = end_date
            schedule.state = "configuring"
            schedule.action_state = ""
            db.add(schedule)
        # Send the job information about job in the 'configuring' state
        if schedule.state == "configuring":
            result[schedule.node_name] = conf_prop
            result[schedule.node_name]["start_date"] = schedule.start_date
            result[schedule.node_name]["end_date"] = schedule.end_date
    close_session(db)
    return json.dumps(result)


def node_deploy(arg_dict):
    # Check the parameters
    if "user" not in arg_dict or "@" not in arg_dict["user"] or "nodes" not in arg_dict:
        error_msg = {
            "parameters": {
                "user": "email@is.fr",
                "nodes": {
                    "node-3": { "node_bin": "my_bin", "environment": "my-env" }
                }
            }
        }
        return json.dumps(error_msg)
    # Check the nodes dictionnary
    node_prop = arg_dict["nodes"]
    if isinstance(node_prop, dict):
        for val in node_prop.values():
            if not isinstance(val, dict):
                return json.dumps(error_msg)
    else:
        return json.dumps(error_msg)
    result = {}
    # Add the properties to the job configuration
    for node_name in node_prop:
        result[node_name] = {}
        my_prop = node_prop[node_name]
        if "node_bin" not in my_prop or len(my_prop["node_bin"]) == 0:
            if "missing" not in result[node_name]:
                result[node_name]["missing"] = [ "node_bin" ]
            else:
                result[node_name]["missing"].append("node_bin")
        if "environment" not in my_prop or len(my_prop["environment"]) == 0:
            if "missing" not in result[node_name]:
                result[node_name]["missing"] = [ "environment" ]
            else:
                result[node_name]["missing"].append("environment")
        if len(result[node_name]) == 0:
            # Remove special characters from the node bin name
            node_bin = safe_string(my_prop["node_bin"])
            # Remove spaces from value
            node_bin = node_bin.replace(" ", "_")
            # Record the job configuration to the database
            db = open_session()
            my_job = db.query(Schedule).filter(Schedule.node_name == node_name).first()
            if my_job is None:
                logging.error("job %s not found in the Schedule DB table" % node_name)
            else:
                my_job.bin = node_bin
                my_job.state = "ready"
                env = ActionProperty()
                env.owner = arg_dict["user"]
                env.node_name = my_job.node_name
                env.prop_name = "environment"
                env.prop_value = my_prop["environment"]
                db.add(env)
                ssh_key = ActionProperty()
                ssh_key.owner = arg_dict["user"]
                ssh_key.node_name = my_job.node_name
                ssh_key.prop_name = "ssh_key"
                if "form_ssh_key" in my_prop and len(my_prop["form_ssh_key"]) > 0:
                    ssh_key.prop_value = my_prop["form_ssh_key"]
                    db.add(ssh_key)
                elif "account_ssh_key" in my_prop and len(my_prop["account_ssh_key"]) > 0:
                    ssh_key.prop_value = my_prop["account_ssh_key"]
                    db.add(ssh_key)
                close_session(db)
                result[node_name] = { "state": "ready" }
    return json.dumps(result)


def node_deployagain(arg_dict):
    result = {}
    # Check POST data
    if "nodes" not in arg_dict or "user" not in arg_dict:
        return json.dumps({
            "parameters": {
                "user": "email@is.fr",
                "nodes": ["name1", "name2" ]
            }
        })
    wanted = arg_dict["nodes"]
    user = arg_dict["user"]
    if len(user) == 0 or '@' not in  user:
        for n in wanted:
            result[n] = "no_email"
        return json.dumps(result)
    # Get information about the requested nodes
    db = open_session()
    nodes = db.query(Schedule
            ).filter(Schedule.node_name.in_(wanted)
            ).filter(Schedule.owner == user
            ).all()
    for n in nodes:
        if n.state == "ready":
            node_action = db.query(Action).filter(Action.node_name == n.node_name).first()
            if node_action is not None:
                db.delete(node_action)
            # The deployment is completed, add a new action
            node_action = new_action(n, db)
            # The deployment is completed, add a new action
            init_action_process(node_action, "deploy")
            db.add(node_action)
            result[n.node_name] = "success"
        else:
            result[n.node_name] = "failure: %s is not ready" % n.node_name
    close_session(db)
    # Build the result
    for n in wanted:
        if n not in result:
            result[n] = "failure"
    return json.dumps(result)


def node_destroy(arg_dict):
    # Check POST data
    if "nodes" not in arg_dict or "user" not in arg_dict:
        return json.dumps({
            "parameters": {
                "user": "email@is.fr",
                "nodes": ["name1", "name2" ]
            }
        })
    wanted = arg_dict["nodes"]
    user = arg_dict["user"]
    if len(user) == 0 or '@' not in  user:
        for n in wanted:
            result[n] = "no_email"
        return json.dumps(result)
    logging.info("Destroying the nodes: %s" % wanted)
    result = {}
    db = open_session()
    # Delete actions in progress for the nodes to destroy
    actions = db.query(Action).filter(Action.node_name.in_(wanted)).all()
    for action in actions:
        db.delete(action)
    # Get the reservations to destroy
    nodes = db.query(Schedule
            ).filter(Schedule.node_name.in_(wanted)
            ).filter(Schedule.owner == user
            ).all()
    for n in nodes:
        # Create a new action to start the destroy action
        node_action = new_action(n, db)
        init_action_process(node_action, "destroy")
        db.add(node_action)
        result[n.node_name] = "success"
    close_session(db)
    # Build the result
    for n in wanted:
        if n not in result:
            result[n] = "failure"
    return json.dumps(result)


def node_extend(arg_dict):
    result = {}
    # Check POST data
    if "nodes" not in arg_dict or "user" not in arg_dict:
        return json.dumps({
            "parameters": {
                "user": "email@is.fr",
                "nodes": ["name1", "name2" ]
            }
        })
    wanted = arg_dict["nodes"]
    user = arg_dict["user"]
    if len(user) == 0 or '@' not in  user:
        for n in wanted:
            result[n] = "no_email"
        return json.dumps(result)
    # Get information about the requested nodes
    db = open_session()
    nodes = db.query(Schedule
            ).filter(Schedule.node_name.in_(wanted)
            ).filter(Schedule.owner == user
            ).all()
    for n in nodes:
        # Allow users to extend their reservation 4 hours before the end_date
        if n.end_date - int(time.time()) < 4 * 3600:
            hours_added = int((n.end_date - n.start_date) / 3600)
            api_url = "https://api.grid5000.fr/stable/sites/%s/internal/oarapi/jobs/%s.json" % (
                get_config()["g5k_site"], n.node_name)
            g5k_login = (arg_dict["g5k_user"], decrypt_password(arg_dict["g5k_password"]))
            json_data = {"method":"walltime-change", "walltime":"+%d:00" % hours_added }
            r = requests.post(url = api_url, auth = g5k_login, json = json_data)
            if r.status_code == 202:
                if r.json()["status"] == "Accepted":
                    n.end_date += hours_added * 3600
                    result[n.node_name] = "success"
                else:
                    error_msg = "failure: walltime modification rejected"
                    logging.error(error_msg)
                    logging.error(r.json())
                    result[n.node_name] = error_msg
            else:
                error_msg = "failure: wrong API return code %d" % r.status_code
                logging.error(error_msg)
                result[n.node_name] = error_msg
        else:
            result[n.node_name] = "failure: it is too early to extend the reservation"
    close_session(db)
    # Build the result
    for n in wanted:
        if n not in result:
            result[n] = "failure"
    return json.dumps(result)


def node_hardreboot(arg_dict):
    result = {"error": "this operation is not available from g5k nodes"}
    return json.dumps(result)


def node_list(arg_dict):
    g5k_site = g5k_connect(arg_dict)
    return json.dumps(build_server_list(g5k_site))


def node_mine(arg_dict):
    if "user" not in arg_dict or "@" not in arg_dict["user"] or \
        "g5k_user" not in arg_dict or "g5k_password" not in arg_dict:
            return json.dumps({
                "parameters": {
                    "user": "email@is.fr",
                    "g5k_user": "my_user",
                    "g5k_password": "encrypted_pwd"
                }
            })
    result = { "states": [], "nodes": {} }
    # Get the list of the states for the 'deploy' process
    py_module = import_module("%s.states" % get_config()["node_type"])
    PROCESS = getattr(py_module, "PROCESS")
    for p in PROCESS["deploy"]:
        if len(p["states"]) > len(result["states"]):
            result["states"] = p["states"]
    # Get the existing job for this user
    db = open_session()
    schedule = db.query(Schedule
        ).filter(Schedule.owner == arg_dict["user"]
        ).filter(Schedule.state != "configuring"
        ).all()
    db_jobs = { sch.node_name: sch for sch in schedule }
    if len(db_jobs) == 0:
        close_session(db)
        return json.dumps(result)
    # Connect to the grid5000 API
    g5k_site = g5k_connect(arg_dict)
    user_jobs = g5k_site.jobs.list(state = "running", user = arg_dict["g5k_user"])
    user_jobs += g5k_site.jobs.list(state = "waiting", user = arg_dict["g5k_user"])
    check_deleted_jobs(db_jobs, user_jobs, db)
    for j in user_jobs:
        j.refresh()
        uid_str = str(j.uid)
        if uid_str in db_jobs:
            my_conf = db_jobs[uid_str]
            result["nodes"][uid_str] = {
                "node_name": uid_str,
                "bin": my_conf.bin,
                "start_date": my_conf.start_date,
                "end_date": my_conf.end_date,
                "state": my_conf.state,
                "job_state": j.state
            }
            assigned_nodes = db.query(ActionProperty
                ).filter(ActionProperty.node_name == my_conf.node_name
                ).filter(ActionProperty.prop_name == "assigned_nodes"
                ).first()
            if assigned_nodes is None:
                if len(j.assigned_nodes) > 0:
                    assigned_nodes = ActionProperty()
                    assigned_nodes.owner = arg_dict["user"]
                    assigned_nodes.node_name = my_conf.node_name
                    assigned_nodes.prop_name = "assigned_nodes"
                    assigned_nodes.prop_value = ",".join(j.assigned_nodes)
                    db.add(assigned_nodes)
                    result["nodes"][uid_str]["assigned_nodes"] = assigned_nodes.prop_value
            else:
                result["nodes"][uid_str]["assigned_nodes"] = assigned_nodes.prop_value
    close_session(db)
    return json.dumps(result)


def node_reserve(arg_dict):
    # Check arguments
    if "filter" not in arg_dict or "user" not in arg_dict or \
        "start_date" not in arg_dict or "duration" not in arg_dict or \
        "g5k_user" not in arg_dict or "g5k_password" not in arg_dict:
            logging.error("Missing parameters: '%s'" % arg_dict)
            return json.dumps({
                "parameters": {
                    "user": "email@is.fr",
                    "filter": "{...}",
                    "start_date": 1623395254,
                    "duration": 3,
                    "g5k_password": "my_encrypted_pwd",
                    "g5k_user": "my_user"
                }
            })
    result = { "nodes": [] }
    user = arg_dict["user"]
    f = arg_dict["filter"]
    # f = {'nb_nodes': '3', 'model': 'RPI4B8G', 'switch': 'main_switch'}
    nb_nodes = int(f["nb_nodes"])
    del f["nb_nodes"]
    start_date = arg_dict["start_date"]
    end_date = start_date + arg_dict["duration"] * 3600
    # Connect to the grid5000 API
    g5k_site = g5k_connect(arg_dict)
    # Get the node list
    servers = build_server_list(g5k_site)
    filtered_nodes = []
    if "name" in f:
        if f["name"] in servers:
            filtered_nodes.append(f["name"])
    else:
        # Get the node properties used in the filter
        node_props = {}
        if len(f) == 0:
            filtered_nodes += servers.keys()
        else:
            for node in servers.values():
                ok_filtered = True
                for prop in f:
                    if node[prop] != f[prop]:
                        ok_filtered = False
                if ok_filtered:
                    filtered_nodes.append(node["name"])
    # Check the availability of the filtered nodes
    logging.info("Filtered nodes: %s" % filtered_nodes)
    selected_nodes = []
    node_status = {}
    for node_name in filtered_nodes:
        cluster_name = node_name.split("-")[0]
        if cluster_name not in node_status:
            node_status[cluster_name] = status_to_reservations(g5k_site.clusters[cluster_name].status.list().nodes)
        ok_selected = True
        # Move the start date back 15 minutes to give the time for destroying the previous reservation
        back_date = start_date - 15 * 60
        # Check the schedule of the existing reservations
        if node_name in node_status[cluster_name]:
            for reservation in node_status[cluster_name][node_name]:
                # Only one reservation for a specific node per user
                if reservation["owner"] == user:
                    ok_selected = False
                # There is no reservation at the same date
                if (back_date > reservation["start_date"] and back_date < reservation["end_date"]) or (
                    back_date < reservation["start_date"] and end_date > reservation["start_date"]):
                    ok_selected = False
        if ok_selected:
            # Add the node to the reservation
            selected_nodes.append(node_name)
            if len(selected_nodes) == nb_nodes:
                # Exit when the required number of nodes is reached
                break;
    logging.info("Selected nodes: %s" % selected_nodes)
    # Set the duration of the job
    walltime = "%s:00" % arg_dict["duration"]
    # Set a 'sleep' command that lasts 30 days, i.e, the maximum duration of this job.
    # This command allows to extend the reservation (see node_extend())
    command = "sleep %d" % (30 * 24 * 3600)
    job_conf = {
        "name": "piseduce %s" % datetime.now(),
        "resources": "nodes=%d,walltime=%s" % (len(selected_nodes), walltime),
        "command": command,
        "types": [ "deploy" ]
    }
    # Set the 'reservation' property to define the job's start date
    now = int(time.time())
    delta_s = start_date - now
    if  delta_s > 5 * 60:
        # Only consider the start_date if this date is after the next 5 minutes
        local_date = datetime.fromtimestamp(start_date).astimezone(pytz.timezone("Europe/Paris"))
        job_conf["reservation"] = str(local_date)[:-6]
    if len(selected_nodes) == 1:
        # Reserve the node from its server name
        logging.info("Reservation the node '%s' with the walltime '%s'" %(
            selected_nodes[0], walltime))
        job_conf["properties"] = "(host in ('%s.%s.grid5000.fr'))" % (
            selected_nodes[0], g5k_site.uid)
    else:
        # Reserve the nodes from cluster names
        clusters = set()
        for node in selected_nodes:
            clusters.add(node.split("-")[0])
        logging.info("Reservation on the clusters '%s' with the walltime '%s'" %(
            clusters, walltime))
        job_conf["properties"] = "(cluster in (%s))" % ",".join(["'%s'" % c for c in clusters])
    try:
        job = g5k_site.jobs.create(job_conf)
        result["nodes"] = selected_nodes
        # Store the g5k login/password to the DB in order to use it with agent_exec.py
        db = open_session()
        g5k_cred = ActionProperty()
        g5k_cred.node_name = job.uid
        g5k_cred.owner = arg_dict["user"]
        g5k_cred.prop_name = "g5k"
        g5k_cred.prop_value = "%s/%s" % (arg_dict["g5k_user"], arg_dict["g5k_password"])
        db.add(g5k_cred)
        close_session(db)
    except:
        logging.exception("Creating job: ")
    return json.dumps(result)


def node_schedule(arg_dict):
    result = { "nodes": {} }
    # Connect to the grid5000 API
    g5k_site = g5k_connect(arg_dict)
    # Get the list of servers
    servers = build_server_list(g5k_site)
    reservations = status_to_reservations(g5k_site.status.list().nodes)
    for node_name in reservations:
        if node_name in servers:
            if node_name not in result["nodes"]:
                result["nodes"][node_name] = {}
            for resa in reservations[node_name]:
                # Round the end_date up to the next hour
                remains = resa["end_date"] % 3600
                if remains == 0:
                    end_date_comp = resa["end_date"]
                else:
                    end_date_comp = resa["end_date"] - remains + 3600
                # Iterate over hours between start_date and end_date
                hours_added = 0
                while resa["start_date"] + hours_added * 3600 < end_date_comp:
                    new_date = resa["start_date"] + hours_added * 3600
                    result["nodes"][node_name][new_date] = {
                        "owner": resa["owner"],
                        "start_hour": resa["start_date"],
                        "end_hour": resa["end_date"]
                    }
                    hours_added += 1
    return json.dumps(result)


def node_state(arg_dict):
    result = { "nodes": {} }
    nodes = []
    db = open_session()
    # Get the jobs in the schedule by reading the DB
    schedule = db.query(Schedule).filter(Schedule.owner == arg_dict["user"]).all()
    uids = { sch.node_name: sch for sch in schedule}
    # Connect to the grid5000 API
    g5k_site = g5k_connect(arg_dict)
    # Get the grid5000 jobs for the grid5000 user
    user_jobs = g5k_site.jobs.list(state = "running", user = arg_dict["g5k_user"])
    user_jobs += g5k_site.jobs.list(state = "waiting", user = arg_dict["g5k_user"])
    # Deleted jobs that do not exist anymore
    check_deleted_jobs(uids, user_jobs, db)
    # Get the jobs in the schedule
    if "nodes" in arg_dict:
        nodes = db.query(Schedule
            ).filter(Schedule.node_name.in_(arg_dict["nodes"])
            ).filter(Schedule.state != "configuring"
            ).all()
    elif "user" in arg_dict:
        nodes = db.query(Schedule
            ).filter(Schedule.owner == arg_dict["user"]
            ).filter(Schedule.state != "configuring"
            ).all()
    # Get the state of the nodes
    for n in nodes:
        result["nodes"][n.node_name] = { "name": n.node_name, "state": n.state, "bin": n.bin }
        if n.state == "in_progress":
            # An action is in progress, get the state of this action
            action = db.query(Action.state).filter(Action.node_name == n.node_name).first()
            if action is None or action.state is None or len(action.state) == 0:
                result["nodes"][n.node_name]["state"] = n.state
            else:
                result["nodes"][n.node_name]["state"] = action.state.replace("_post", "").replace("_exec", "")
        if n.state == "ready":
            # There is no action associated to this node
            if n.action_state is not None and len(n.action_state) > 0:
                result["nodes"][n.node_name]["state"] = n.action_state
    close_session(db)
    return json.dumps(result)


def switch_list(arg_dict):
    return json.dumps({ "error": "Switch list is not available from g5k agents" })


def switch_consumption(arg_dict):
    return json.dumps({ "error": "Switch consumption is not available from g5k agents" })
