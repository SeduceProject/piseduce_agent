from api.auth import auth
from flask import Blueprint
from lib.config_loader import get_config
from importlib import import_module
import flask


user_v1 = Blueprint("user_v1", __name__)
# Get the python module from the type of the nodes managed by this agent
node_type = get_config()["node_type"]
api_exec_mod = import_module("%s.api" % node_type)


# List the DHCP clients (only used by administrators but the URL must be in /user/)
@user_v1.route("/client/list", methods=["POST"])
@auth
def client_list():
    """
    Return the list of the DHCP clients read from the '/etc/dnsmasq.conf' file.
    JSON parameters: none.
    Example of return value:
    {
        'switch1': {'mac_address': 'c4:41:1e:11:11:11', 'ip': '4.4.0.8'},
        'node-1': {'mac_address': 'dc:a6:32:12:12:12', 'ip': '4.4.0.11'},
        'node-2': {'mac_address': 'dc:a6:32:12:12:12', 'ip': '4.4.0.12'}
    }
    """
    return getattr(api_exec_mod, "client_list")(flask.request.json)


# List the switches (only used by administrators but the URL must be in /user/)
@user_v1.route("/switch/list", methods=["POST"])
@auth
def switch_list():
    """
    Return the list of the managed switches.
    JSON parameters: none.
    Example of return value:
    {
        'switch1': {
            'ip': '4.4.0.4',
            'community': 'switchcom',
            'port_nb': '8',
            'first_ip': '1',
            'master_port': '8',
            'poe_oid': 'iso.3.6.1.2.1.105.1.1.1.3.1',
            'oid_offset': '48',
            'power_oid': 'iso.3.6.1.2.1.105.1.1.1.3.1'
        }
    }
    """
    return getattr(api_exec_mod, "switch_list")(flask.request.json)


# List the switches (only used by administrators but the URL must be in /user/)
@user_v1.route("/switch/consumption", methods=["POST"])
@auth
def switch_consumption():
    """
    Read the power consumption of the ports of the switch from the Influx DB.
    JSON parameters: 'period'
    Example of return value:
    [
        {
            "time": 1631101186,
            "consumption": 4.9,
            "port": "1",
            "switch": "RPI3_SW"
        },
        {
            "time": 1631101188,
            "consumption": 0.0,
            "port": "24",
            "switch": "RPI4_SW"
        },
        {
            "time": 1631101186,
            "consumption": 0.0,
            "port": "17",
            "switch": "RPI3_SW"
        }
    ]
    """
    return getattr(api_exec_mod, "switch_consumption")(flask.request.json)


@user_v1.route("/environment/register", methods=["POST"])
@auth
def register_environment():
    """
    Register the environment that belongs to the Raspberry specified in the parameters.
    JSON parameters: 'node_name', 'img_path', 'env_name'.
    Example of return value:
    {
        'environment': 'env_name'
    }
    """
    return getattr(api_exec_mod, "register_environment")(flask.request.json)


# List the environments (only used by administrators but the URL must be in /user/)
@user_v1.route("/environment/list", methods=["POST"])
@auth
def environment_list():
    """
    Return the list of the node environments.
    JSON parameters: none.
    Example of return value:
    {
        'env1': {
            'img_name': 'raspios-buster-armhf-lite.img.tar.gz',
            'img_size': '1849688064',
            'sector_start': '532480'
        }
    }
    """
    return getattr(api_exec_mod, "environment_list")(flask.request.json)


# List the switches (only used by administrators but the URL must be in /user/)
@user_v1.route("/node/temperature", methods=["POST"])
@auth
def node_temperature():
    """
    Read the power consumption of the ports of the switch from the Influx DB.
    JSON parameters: 'period'
    Example of return value:
    [
        {
            "time": 1631101186,
            "consumption": 49,
            "node": "imt-1"
        },
        {
            "time": 1631101188,
            "consumption": 60,
            "node": "imt-23"
        },
        {
            "time": 1631101186,
            "consumption": 59,
            "node": "imt-23"
        }
    ]
    """
    return getattr(api_exec_mod, "node_temperature")(flask.request.json)


@user_v1.route("/node/state", methods=["POST"])
@auth
def node_state():
    """
    Return the state of the nodes and other properties to display on the manage page.
    Returned properties for every node: name, state, bin.
    Other properties can be added to the returned properties.
    JSON parameters: 'nodes' or 'user'.
    Example of return value:
    {
        "nodes": {
            "node-1": {
                "name": "node-1", "state": "ready", "bin": "first_bin",
                "os_password": "toto", "optional_prop": "my_value"
            },
            "node-2": {
                "name": "node-2", "state": "env_check", "bin": "first_bin"
                "another_optional_prop": "my_value"
            },
            "node-3": {
                "name": "node-2", "state": "deployed", "bin": "second_bin"
            }
        }
    }
    """
    return getattr(api_exec_mod, "node_state")(flask.request.json)


@user_v1.route("/node/schedule", methods=["POST"])
@auth
def node_schedule():
    """
    Return the list of reservations.
    JSON parameters: none.
    Example of return value:
    {
        'nodes': {
            'node-5': {
                '2021-05-31': {
                    'admin@piseduce.fr': {
                        'hours': ['9', '10', '11', '12', '13'],
                        'owner': 'admin@piseduce.fr',
                        'start_hour': '09:09:00',
                        'end_hour': '13:09:00'
                    }
                }
            },
            'node-3': {
                '2021-05-31': {
                    'admin@piseduce.fr': {
                        'hours': ['21', '22', '23'],
                        'owner': 'admin@piseduce.fr',
                        'start_hour': '21:18:00',
                        'end_hour': '01:18:00'
                    }
                },
                '2021-06-01': {
                    'admin@piseduce.fr': {
                        'hours': ['0', '1'],
                        'owner': 'admin@piseduce.fr',
                        'start_hour': '21:18:00',
                        'end_hour': '01:18:00'
                    }
                }
            }
        }
    }
    """
    return getattr(api_exec_mod, "node_schedule")(flask.request.json)


# Get the list of the nodes with their properties
@user_v1.route("/node/list", methods=["POST"])
@auth
def node_list():
    """
    Return the list of nodes with their properties.
    JSON parameters: none.
    Example of return value:
    {
        "node-1": {
            "cpu_nb": 2,
            "memory": 8,
        },
        "node-2": {
            "cpu_nb": 4,
            "memory": 4,
        },
        "node-3": {
            "cpu_nb": 2,
            "memory": 8,
        }
    }
    """
    return getattr(api_exec_mod, "node_list")(flask.request.json)


@user_v1.route("/node/mine", methods=["POST"])
@auth
def node_mine():
    """
    Return the list of deployment states and the list of my nodes that are deploying.
    The nodes in the 'configuring' state are excluded!
    JSON parameters: user.
    Example of return value:
    {
        "states": [
            "boot_conf",
            "turn_off",
            "turn_on",
            "ssh_test",
            "env_copy",
            "env_check",
            "delete_partition",
            "create_partition",
            "mount_partition",
            "resize_partition",
            "wait_resizing",
            "system_conf",
            "boot_files",
            "ssh_test",
            "system_update",
            "boot_update",
            "user_conf",
            "deployed"
        ],
        "nodes": {
            "node-1": {
                "node_name": "node-1",
                "owner": "admin@piseduce.fr",
                "bin": "test",
                "start_date": "2021-06-04 09:43:00",
                "end_date": "2021-06-04 11:43:00",
                "state": "ready",
                "action_state": "",
                "ip": "4.4.4.1",
                "model": "RPI3B+1G",
                "port_number": "3",
                "serial": "abcdef1",
                "switch": "24port_RPI3",
                "environment": "raspbian_buster_32bit"
            },
            "node-3": {
                "node_name": "node-3",
                "owner": "admin@piseduce.fr",
                "bin": "test",
                "start_date": "2021-06-04 09:43:00",
                "end_date": "2021-06-04 11:43:00",
                "state": "ready",
                "action_state": "",
                "ip": "4.4.4.3",
                "model": "RPI3B+1G",
                "port_number": "5",
                "serial": "abcdef3",
                "switch": "24port_RPI3",
                "environment": "raspbian_buster_32bit"
            }
        }
    }
    """
    return getattr(api_exec_mod, "node_mine")(flask.request.json)


## Actions
@user_v1.route("/reserve", methods=["POST"])
@auth
def reserve():
    """
    Reserve the nodes selected by the user filters.
    JSON parameters: 'user', 'filter', 'start_date', 'duration'.
    Example of return value:
    { "nodes": [ "node-1", "node-3", "node-5" ] }
    """
    json_data = flask.request.json
    # Remove useless filter properties
    if "agent" in json_data["filter"]:
        del json_data["filter"]["agent"]
    if "type" in json_data["filter"]:
        del json_data["filter"]["type"]
    return getattr(api_exec_mod, "node_reserve")(json_data)


@user_v1.route("/configure", methods=["POST"])
@auth
def configure():
    """
    Return the nodes in the 'configuring' state and
    the properties to provide to configure the nodes.
    JSON parameters: 'user'.
    Example of return value:
    {
        'soupirs-5': {
            'node_bin': { 'values': [], 'mandatory': True },
            'environment': { 'values': ['raspbian_buster_32bit'], 'mandatory': True },
            'form_ssh_key': { 'values': [], 'mandatory': False },
            'start_date': '2021-05-31 09:09:00',
            'end_date': '2021-05-31 13:09:00'
        },
        'soupirs-3': {
            'node_bin': {'values': [], 'mandatory': True},
            'environment': {'values': ['raspbian_buster_32bit'], 'mandatory': True},
            'form_ssh_key': {'values': [], 'mandatory': False},
            'start_date': '2021-05-31 21:18:00',
            'end_date': '2021-06-01 01:18:00'
        }
    }
    """
    return getattr(api_exec_mod, "node_configure")(flask.request.json)


@user_v1.route("/deploy", methods=["POST"])
@auth
def deploy():
    """
    Set the deployment properties of the nodes. After this operation,
    nodes are in the 'ready' state.
    JSON parameters: 'user', nodes properties.
    POST data (input) example:
    {
        "user": "admin@piseduce.fr",
        "nodes": {
            "node-1": {
                "node_bin": "first bin",
                "environment": "raspbian",
                "update_os": "no"
            },
            "node-2": {
                "node_bin": "first bin",
                "environment": "raspbian",
                "update_os": "no"
            }
        }
    }
    Example of return value:
    {
        "node-1": { "state": "ready" },
        "node-2": { "state": "ready" }
    }
    """
    return getattr(api_exec_mod, "node_deploy")(flask.request.json)


@user_v1.route("/destroy", methods=["POST"])
@auth
def destroy():
    """
    Destroy the reservation associated to the nodes.
    JSON parameters: 'user', 'nodes'.
    Example of return value:
    {
        "node-1": "success",
        "node-2": "success"
    }
    """
    return getattr(api_exec_mod, "node_destroy")(flask.request.json)


@user_v1.route("/hardreboot", methods=["POST"])
@auth
def hardreboot():
    """
    Hard reboot (turn off then turn on) the nodes.
    JSON parameters: 'user', 'nodes'.
    Example of return value:
    {
        "node-1": "success",
        "node-2": "success"
    }
    """
    return getattr(api_exec_mod, "node_hardreboot")(flask.request.json)


@user_v1.route("/bootfiles", methods=["POST"])
@auth
def bootfiles():
    """
    Upload the boot files (/boot/*) to the TFTP server.
    JSON parameters: 'user', 'nodes'.
    Example of return value:
    {
        "node-1": "success",
        "node-2": "success"
    }
    """
    return getattr(api_exec_mod, "node_bootfiles")(flask.request.json)


@user_v1.route("/deployagain", methods=["POST"])
@auth
def deployagain():
    """
    Deploy again the nodes.
    JSON parameters: 'user', 'nodes'.
    Example of return value:
    {
        "node-1": "success",
        "node-2": "success"
    }
    """
    return getattr(api_exec_mod, "node_deployagain")(flask.request.json)


# Increase the duration of existing reservations
@user_v1.route("/extend", methods=["POST"])
@auth
def extend():
    """
    Extend the reservations by postponing the end date to a later date.
    JSON parameters: 'user', 'nodes'.
    Example of return value:
    {
        "node-1": "success",
        "node-2": "success"
    }
    """
    return getattr(api_exec_mod, "node_extend")(flask.request.json)
