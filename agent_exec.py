# Load the configuration file
import sys
from lib.config_loader import load_config, get_config
if len(sys.argv) != 2:
    print("The configuration file is required in parameter.")
    print("For example, 'python3 %s config.json'" % sys.argv[0])
    sys.exit(2)
load_config(sys.argv[1])

from database.connector import open_session, close_session
from database.tables import Action, ActionProperty, RaspNode, Schedule
from datetime import datetime
from importlib import import_module
from lib.config_loader import load_config
from sqlalchemy import or_
import logging, os, subprocess, sys, time


# Import the action driver from config_agent.json
node_type = get_config()["node_type"]
# Import the action executor module
exec_action_mod = import_module("%s.exec" % node_type)
# Import the PROCESS and STATE_DESC variables
py_module = import_module("%s.states" % node_type)
PROCESS = getattr(py_module, "PROCESS")
STATE_DESC = getattr(py_module, "STATE_DESC")


# Move the action to the next state of the process
def next_state_move(db_action):
    # Select the state list from the environment
    state_list = []
    for process in PROCESS[db_action.process]:
        if len(process["environments"]) == 0 or db_action.environment in process["environments"]:
            state_list = process["states"]
    if len(state_list) == 0:
        db_action.state = "lost"
        logging.error("[%s] no state list for the '%s' process and the '%s' environment" % (
            db_action.node_name, db_action.process, db_action.environment))
        return False
    # Increase the state index of the action
    if db_action.state_idx is None:
        db_action.state_idx = 0
    else:
        if (db_action.state_idx + 1) < len(state_list):
            db_action.state_idx += 1
        else:
            logging.error("[%s] no more state (index: %d) in the '%s' process" % (
                db_action.node_name, db_action.state_idx, db_action.process))
            db_action.state = "lost"
            return False
    # Set the state of the action to the next state of the process
    db_action.state = state_list[db_action.state_idx]
    db_action.updated_at = int(time.time())
    logging.info("[%s] changes to the '%s' state" % (db_action.node_name, db_action.state))
    return True


def new_action(db_node, db):
    # Delete existing actions
    existing = db.query(Action).filter(Action.node_name == db_node.node_name).all()
    for e in existing:
        db.delete(e)
    # Get the node IP (only for Raspberry agents)
    if get_config()["node_type"] == "raspberry":
        node_ip = db.query(RaspNode).filter(RaspNode.name == db_node.node_name).first().ip
    else:
        node_ip = None
    # Add a new action
    act = Action()
    act_prop = db.query(ActionProperty
        ).filter(ActionProperty.node_name == db_node.node_name
        ).filter(ActionProperty.prop_name == "environment"
        ).first()
    if act_prop is not None:
        act.environment = act_prop.prop_value
    act.node_name = db_node.node_name
    if node_ip is not None:
        act.node_ip = node_ip
    db_node.state = "in_progress"
    return act


def save_reboot_state(db_action, db):
    reboot_str = ""
    reboot_state = db.query(ActionProperty
        ).filter(ActionProperty.node_name == db_action.node_name
        ).filter(ActionProperty.prop_name == "reboot_state"
        ).first()
    if db_action.state_idx is None:
        # This is an hardreboot action initiated by the user, check if the node is deployed
        is_deployed = db.query(Schedule
            ).filter(Schedule.node_name == db_action.node_name
            ).filter(Schedule.action_state == "deployed"
            ).first()
        if is_deployed is not None:
            for process in PROCESS["deploy"]:
                if len(process["environments"]) == 0 or db_action.environment in process["environments"]:
                    reboot_str = "deploy?!%d" % (len(process["states"]) - 1)
    else:
        reboot_str = "%s?!%d" % (db_action.process, db_action.state_idx)
    if len(reboot_str) > 0:
        # Remember the last state of the current process
        if reboot_state is None:
            owner_email = db.query(ActionProperty
                ).filter(ActionProperty.node_name == db_action.node_name
                ).first().owner
            reboot_prop = ActionProperty()
            reboot_prop.node_name = db_action.node_name
            reboot_prop.prop_name = "reboot_state"
            reboot_prop.prop_value = reboot_str
            reboot_prop.owner = owner_email
            db.add(reboot_prop)
        else:
            reboot_state.prop_value = reboot_str


def init_action_process(db_action, process_name):
    db_action.process = process_name
    db_action.state_idx = None
    db_action.state = None
    next_state_move(db_action)


def load_reboot_state(db_action, db):
    reboot_state = db.query(ActionProperty
        ).filter(ActionProperty.node_name == db_action.node_name
        ).filter(ActionProperty.prop_name == "reboot_state"
        ).first()
    if reboot_state is not None and reboot_state.prop_value is not None and len(reboot_state.prop_value) > 0:
        logging.info("[%s] load the reboot state '%s'" % (db_action.node_name, reboot_state.prop_value))
        process_info = reboot_state.prop_value.split("?!")
        if len(process_info) == 2:
            db_action.process = process_info[0]
            idx = int(process_info[1])
            if idx == 0:
                db_action.state_idx = None
            else:
                db_action.state_idx = idx - 1
            next_state_move(db_action)
            return True
        else:
            logging.error("[%s] can not find the process for the '%s' state" % (
                db_action.node_name, reboot_state.prop_value))
    else:
        logging.error("[%s] can not detect the reboot_state" % db_action.node_name)
    return False


def free_reserved_node(db, node_name):
    # Delete action properties
    properties = db.query(ActionProperty).filter(ActionProperty.node_name == node_name).all()
    for prop in properties:
        db.delete(prop)
    # Delete reservations to the schedule
    reservations = db.query(Schedule).filter(Schedule.node_name == node_name).all()
    for res in reservations:
        db.delete(res)


if __name__ == "__main__":
    # This file used by the SystemD service
    STOP_FILE = "execstop"
    # Logging configuration
    logging.basicConfig(filename='info_exec.log', level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("## Starting the agent executor")
    # Detect the final states
    final_states = [ "lost" ]
    for state in STATE_DESC:
        if not STATE_DESC[state]["exec"] and not STATE_DESC[state]["post"]:
            final_states.append(state)
    logging.info("### Final states: %s" % final_states)
    # Connection to the database
    db = open_session()
    # Register the information about the pimaster (me)
    # Get the user account (this should be the root account)
    if "user" in get_config():
        my_user = get_config()["user"]
    else:
        cmd = "whoami"
        process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        my_user = process.stdout.decode("utf-8").strip()
    # Get the private IP address that could be used by the agent to deploy nodes (used to deploy Raspberry)
    if "ip" in get_config():
        my_ip = get_config()["ip"]
    else:
        cmd = "ip route | grep eth0"
        process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        my_ip = process.stdout.decode("utf-8").split()
        print(my_ip)
        if len(my_ip) > 0:
            my_ip = my_ip[8]
        if len(my_ip) == 0 or len(my_ip.split(".")) != 4:
            msg = "Fail to retrieve the pimaster IP. Output: %s" % my_ip
            logging.error(msg)
            print(msg)
            sys.exit(2)
    # Update the pimaster information of the database
    pimaster_info = db.query(RaspNode).filter(RaspNode.name == "pimaster").first()
    if len(my_user) > 0 and len(my_ip) > 0 and len(my_ip.split(".")) == 4:
        if pimaster_info is not None:
            logging.info("Update the pimaster information from existing DB records")
            # Check the pimaster information
            pimaster_info.switch = my_user
            pimaster_info.ip = my_ip
        else:
            # Add the pimaster information in the database
            logging.info("Create new records to register the pimaster information")
            master_record = RaspNode()
            master_record.name = "pimaster"
            master_record.switch = my_user
            master_record.ip = my_ip
            master_record.model = "master"
            db.add(master_record)
        logging.info("pimaster ip: %s, pimaster user: %s" % (my_ip, my_user))
    else:
        logging.error("can not get the IP or the user of the pimaster: ip=%s, user=%s" % (my_ip, my_user))
        sys.exit(13)
    # Try to configure the lost nodes
    lost_nodes = db.query(Schedule
        ).filter(Schedule.action_state == "lost"
        ).all()
    for node in lost_nodes:
        logging.info("[%s] lost node rescue" % node.node_name)
        # Create a new action to continue the deployment
        act = new_action(node, db)
        # Load the reboot_state
        if load_reboot_state(act, db):
            # The action is successfully configured, add it
            db.add(act)
            # Delete the reboot_state to allow the node to reboot
            reboot_state = db.query(ActionProperty
                ).filter(ActionProperty.node_name == node.node_name
                ).filter(ActionProperty.prop_name == "reboot_state"
                ).first()
            if reboot_state is not None:
                reboot_state.prop_value = None
        else:
            # The reboot action can not be executed
            node.state = "ready"
    close_session(db)
    # Analyzing the database
    while not os.path.isfile(STOP_FILE):
        db = open_session()
        try:
            # Release the expired nodes
            now = int(time.time())
            for node in db.query(Schedule).filter(Schedule.end_date < now).all():
                logging.info("[%s] Destroy the expired reservation (expired date: %s)" % (
                    node.node_name, datetime.fromtimestamp(node.end_date)))
                # The reservation is expired, delete it
                if node.state == "configuring":
                    # The node is not deployed
                    free_reserved_node(db, node.node_name)
                else:
                    # Check if a destroy action is in progress
                    destroy_action = db.query(Action
                        ).filter(Action.node_name == node.node_name
                        ).filter(Action.process == "destroy").all()
                    if len(destroy_action) == 0:
                        node_action = new_action(node, db)
                        init_action_process(node_action, "destroy")
                        db.add(node_action)
            db.commit()
            # Load reboot_state for the actions in the 'rebooted' state or in the 'lost' state
            reboot_actions = db.query(Action).filter(Action.state == "rebooted").all()
            for action in reboot_actions:
                load_reboot_state(action, db)
            # Commit the DB change due to rebooted nodes
            db.commit()
            # Delete the actions in final states
            final_actions = db.query(Action).filter(Action.state.in_(final_states)).all()
            for action in final_actions:
                logging.info("[%s] action is completed (current state: '%s')" % (
                    action.node_name, action.state))
                # Update the action_state of the reservation
                node = db.query(Schedule
                    ).filter(Schedule.state == "in_progress"
                    ).filter(Schedule.node_name == action.node_name
                    ).first()
                if node is not None:
                    node.state = "ready"
                    node.action_state = action.state
                    if action.state == "destroyed":
                        # Update the node fields
                        free_reserved_node(db, node.node_name)
                # Delete the action
                db.delete(action)
            # Start actions for the recently configured nodes
            now = int(time.time())
            pending_nodes = db.query(Schedule
                ).filter(Schedule.state == "ready"
                ).filter(Schedule.action_state == ""
                ).filter(Schedule.start_date < now
                ).all()
            if len(pending_nodes) > 0:
                for node in pending_nodes:
                    logging.info("[%s] starts the deploy process (start date: %s)" % (
                        node.node_name, datetime.fromtimestamp(node.start_date)))
                    act = new_action(node, db)
                    init_action_process(act, "deploy")
                    db.add(act)
            # Process the ongoing actions
            pending_actions = db.query(Action).filter(~Action.state.in_(final_states)
                ).all()
            # Sort the actions according the list of states
            sorted_actions = { key: [] for key in STATE_DESC.keys() }
            for action in pending_actions:
                action_state = action.state.replace("_exec", "").replace("_post","")
                if action_state in sorted_actions:
                    sorted_actions[action_state].append(action)
                else:
                    logging.warning("[%s] unknow state '%s'" % (action.node_name, action.state))
            # Execute the functions of the states
            for state in sorted_actions:
                for action in sorted_actions[state]:
                    state_fct = action.state
                    if not state_fct.endswith("_exec") and not state_fct.endswith("_post"):
                        if STATE_DESC[action.state]["exec"]:
                            state_fct = action.state + "_exec"
                        else:
                            state_fct = action.state + "_post"
                    # Execute the function associated to the action state
                    action_ret = False
                    try:
                        action_ret = getattr(exec_action_mod, state_fct)(action, db)
                    except:
                        logging.exception("[%s]" % action.node_name)
                        sys.exit(42)
                    if action_ret:
                        logging.info("[%s] successfully executes '%s'" % (action.node_name, state_fct))
                        # Update the state of the action
                        if state_fct.endswith("_exec") and STATE_DESC[state]["post"]:
                            # Execute the '_post' function
                            action.state = state_fct.replace("_exec", "_post")
                        else:
                            # Move to the next state of the process
                            next_state_move(action)
                    else:
                        # The node is not ready, test the reboot timeout
                        logging.warning("[%s] fails to execute '%s'" % (action.node_name, state_fct))
                        if action.updated_at is None:
                            action.updated_at = int(time.time())
                        elapsedTime = now - action.updated_at
                        action_state = action.state.replace("_exec", "").replace("_post","")
                        reboot_timeout = STATE_DESC[action_state]["before_reboot"]
                        do_lost = True
                        reboot_str = "%s?!%d" % (action.process, action.state_idx)
                        reboot_state = db.query(ActionProperty
                                ).filter(ActionProperty.node_name == action.node_name
                                ).filter(ActionProperty.prop_name == "reboot_state"
                                ).first()
                        if reboot_timeout > 0 and action.process != "reboot" \
                            and (reboot_state is None or reboot_state.prop_value != reboot_str):
                            do_lost = False
                            if elapsedTime > reboot_timeout:
                                logging.warning("[%s] hard reboot the node" % action.node_name)
                                save_reboot_state(action, db)
                                init_action_process(action, "reboot")
                            else:
                                logging.info("[%s] not ready since %d seconds" % (action.node_name, elapsedTime))
                        # The node is not ready, test the lost timeout
                        lost_timeout = STATE_DESC[action_state]["lost"]
                        if do_lost and lost_timeout > 0:
                            if elapsedTime > lost_timeout:
                                logging.warning("[%s] is lost. Stop monitoring it!" % action.node_name)
                                if action.process != "reboot":
                                    save_reboot_state(action, db)
                                action.state = "lost"
                            else:
                                logging.info("[%s] not ready since %d seconds" %(action.node_name, elapsedTime))
        except Exception as e:
            logging.exception("Node process error")
        close_session(db)
        # Waiting for the node configuration
        time.sleep(3)
    if os.path.isfile(STOP_FILE):
        os.remove(STOP_FILE)
    logging.info("### The piTasks service is stopped.")
