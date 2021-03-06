from api.auth import auth
from api.tool import safe_string
from database.connector import open_session, close_session
from database.tables import Action, ActionProperty, RaspEnvironment, RaspNode, RaspSwitch 
from datetime import datetime
from glob import glob
from lib.config_loader import get_config
from lib.switch_snmp import get_poe_status, switch_test, turn_on_port, turn_off_port
from paramiko.ssh_exception import BadHostKeyException, AuthenticationException, SSHException
from sqlalchemy import distinct
import flask, json, logging, os, paramiko, shutil, socket, subprocess, time


admin_v1 = flask.Blueprint("admin_v1", __name__)


@admin_v1.route("/node/pimaster", methods=["POST"])
@auth
def pimaster_node():
    db = open_session()
    pimaster = db.query(RaspNode).filter(RaspNode.name == "pimaster").first()
    pimaster_ip = "undefined"
    if pimaster is not None:
        pimaster_ip = pimaster.ip
    close_session(db)
    return json.dumps({ "ip": pimaster_ip })


@admin_v1.route("/pimaster/changeip", methods=["POST"])
@auth
def pimaster_changeip():
    new_ip = flask.request.json["new_ip"]
    new_network = new_ip[:new_ip.rindex(".")]
    # Check the static IP configuration
    cmd = "grep '^static ip_address' /etc/dhcpcd.conf"
    process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        universal_newlines=True)
    static_conf = process.stdout.strip()
    if len(static_conf) > 0:
        ip = static_conf.split("=")[1].replace("/24", "")
        network = ip[:ip.rindex(".")]
        # Change the static IP
        cmd = "sed -i 's:=%s/:=%s/:g' /etc/dhcpcd.conf" % (ip, new_ip)
        process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Change the IP of the DHCP server
        cmd = "sed -i 's:=%s:=%s:g' /etc/dnsmasq.conf" % (ip, new_ip)
        process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Change the IP of the DHCP clients
        cmd = "sed -i 's:,%s:,%s:g' /etc/dnsmasq.conf" % (network, new_network)
        process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Delete the DHCP leases
        cmd = "rm /var/lib/misc/dnsmasq.leases"
        process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return json.dumps({ "msg": "IP configuration is successfully changed. You need to reboot pimaster!" })
    else:
        return json.dumps({ "msg": "The agent is not configured with a static IP" })


@admin_v1.route("/node/rename", methods=["POST"])
@auth
def rename_nodes():
    # Received data
    rename_data = flask.request.json
    if "base_name" not in rename_data:
        return json.dumps({ "error": "'base_name' parameter is required" })
    nodes = []
    error = ""
    db = open_session()
    if len(db.query(Action).all()) > 0:
        error = "can not rename the nodes: actions in progress"
    else:
        # Rename all nodes
        for node in db.query(Schedule).all():
            # We assume the node name looks like 'base_name-number'
            current = node.node_name.split("-")[0]
            node.name = node.node_name.replace(current, rename_data["base_name"])
            nodes.append(node.node_name)
        for node in db.query(RaspNode).all():
            # We assume the node name looks like 'base_name-number'
            current = node.node_name.split("-")[0]
            node.name = node.node_name.replace(current, rename_data["base_name"])
        for node in db.query(ActionProperty).all():
            # We assume the node name looks like 'base_name-number'
            current = node.node_name.split("-")[0]
            node.node_name = node.node_name.replace(current, rename_data["base_name"])
    close_session(db)
    if len(error) == 0:
        return json.dumps({ "nodes": nodes })
    else:
        return json.dumps({ "error": error })


# Add a Raspberry environment to the database
@admin_v1.route("/add/environment", methods=["POST"])
@auth
def add_environment():
    json_data = flask.request.json
    env_props = [str(c).split(".")[1] for c in RaspEnvironment.__table__.columns]
    # Check if all properties belong to the POST data
    missing_data = dict([(key_data, []) for key_data in env_props if key_data not in json_data.keys()])
    if len(missing_data) == 0:
        db = open_session()
        existing = db.query(RaspEnvironment).filter(RaspEnvironment.name == json_data["name"]).all()
        for to_del in existing:
            db.delete(to_del)
        new_env = RaspEnvironment()
        new_env.name = json_data["name"]
        new_env.img_name = json_data["img_name"]
        new_env.img_size = json_data["img_size"]
        new_env.sector_start = json_data["sector_start"]
        new_env.ssh_user = json_data["ssh_user"]
        new_env.state = json_data["state"]
        if json_data["web"] == "true" or json_data["web"] == "True" or json_data["web"] == 1:
            new_env.web = True
        else:
            new_env.web = False
        db.add(new_env)
        close_session(db)
        #TODO reload the environments
        return json.dumps({ "environment": json_data["name"] })
    else:
        return json.dumps({ "missing": missing_data })


# Add DHCP clients to the dnsmasq configuration
@admin_v1.route("/add/client", methods=["POST"])
@auth
def add_client():
    # Received data
    dhcp_data = flask.request.json
    del dhcp_data["token"]
    # Required properties to create DHCP clients
    dhcp_props = [ "name", "ip", "mac_address" ]
    # Check if all properties belong to the POST data
    missing_data = dict([ (key_data, []) for key_data in dhcp_props if key_data not in dhcp_data.keys()])
    if len(missing_data) == 0:
        # Check the parameters of the DHCP client
        checks = {}
        for data in dhcp_data:
            checks[data] = { "value": dhcp_data[data] }
        # Get the network IP from the dnsmasq configuration
        cmd = "grep listen-address /etc/dnsmasq.conf"
        process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True)
        network_ip = process.stdout.split("=")[1]
        network_ip = network_ip[:network_ip.rindex(".")]
        # Get the existing IP addresses
        existing_ips = []
        cmd = "grep ^dhcp-host /etc/dnsmasq.conf"
        process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True)
        for line in process.stdout.split('\n'):
            if "," in line and not line.startswith("#"):
                existing_ips.append(line.split(",")[2])
        # Check the provided IP
        ip_check = dhcp_data["ip"].startswith(network_ip) and dhcp_data["ip"] not in existing_ips
        checks["ip"]["check"] = ip_check
        # Check the value looks like a MAC address
        mac_check = len(dhcp_data["mac_address"]) == 17 and len(dhcp_data["mac_address"].split(":")) == 6
        checks["mac_address"]["check"] = mac_check
        # Remove unwanted characters from the name
        dhcp_data["name"] = safe_string(dhcp_data["name"])
        if ip_check and mac_check:
            # Add the DHCP client
            cmd = "echo 'dhcp-host=%s,%s,%s' >> /etc/dnsmasq.conf" % (
                    dhcp_data["mac_address"], dhcp_data["name"], dhcp_data["ip"])
            process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logging.info("[%s] MAC: '%s', IP: '%s'" % (dhcp_data["name"], dhcp_data["mac_address"], dhcp_data["ip"]))
            # Restart dnsmasq
            cmd = "service dnsmasq restart"
            process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return json.dumps({"client": { "name": dhcp_data["name"] } })
        else:
            return json.dumps({"check": checks})
    else:
        return json.dumps({"missing": missing_data })


@admin_v1.route("/add/switch", methods=["POST"])
@auth
def add_switch():
    switch_data = flask.request.json
    del switch_data["token"]
    # Required properties to create switches
    switch_props = [str(c).split(".")[1] for c in RaspSwitch.__table__.columns]
    # Remove computed properties
    switch_props.remove("port_number")
    switch_props.remove("oid_offset")
    switch_props.remove("first_ip")
    # Check if all properties belong to the POST data
    missing_data = dict([ (key_data, []) for key_data in switch_props if key_data not in switch_data.keys()])
    if len(missing_data) == 0:
        checks = {}
        for data in switch_data:
            checks[data] = { "value": switch_data[data] }
        db = open_session()
        existing = db.query(RaspSwitch).filter(RaspSwitch.name == switch_data["name"]).all()
        for to_del in existing:
            db.delete(to_del)
        # Check the IP
        ip_check = False
        cmd = 'ping -c 1 -W 1 %s' % switch_data['ip']
        process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ip_check = process.returncode == 0
        checks["ip"]["check"] = ip_check
        if ip_check:
            # Remove the last digit of the OID
            root_oid = switch_data["poe_oid"]
            root_oid = root_oid[:root_oid.rindex(".")]
            switch_info = switch_test(switch_data["ip"], switch_data["community"], root_oid)
            # Check the SNMP connection
            snmp_check = switch_info["success"]
            checks["community"]["check"] = snmp_check
            checks["poe_oid"]["check"] = snmp_check
        if ip_check and snmp_check:
            db = open_session()
            # Get information about existing switches to reserve the IP range for the nodes connected to the new switch
            all_switches = db.query(RaspSwitch).order_by(RaspSwitch.first_ip).all()
            existing_info = {}
            for sw in all_switches:
                existing_info[sw.name] = {
                    "port_number": sw.port_number, "first_ip": sw.first_ip
                }
            # Choose the last digit of the first IP such as [last_digit, last_digit + port_number] is available
            last_digit = 1
            for sw in existing_info.values():
                new_last = last_digit + switch_info["port_number"] - 1
                if new_last < sw["first_ip"]:
                    # We found the last_digit value
                    break
                else:
                    last_digit = sw["first_ip"] + sw["port_number"]
            if last_digit + switch_info["port_number"] - 1 > 250:
                close_session(db)
                msg = "No IP range available for the switch '%s' with %d ports" % (
                        switch_data["name"], switch_info["port_number"])
                logging.error(msg)
                return json.dumps({ "error": msg })
            # Add the switch
            new_switch = RaspSwitch()
            new_switch.name = switch_data["name"]
            new_switch.ip = switch_data["ip"]
            new_switch.community = switch_data["community"]
            new_switch.port_number = switch_info["port_number"]
            new_switch.first_ip = last_digit
            new_switch.master_port = switch_data["master_port"]
            new_switch.poe_oid = switch_info["poe_oid"]
            new_switch.oid_offset = switch_info["offset"]
            # Remove the last digit of the OID
            power_oid = switch_data["power_oid"]
            new_switch.power_oid = power_oid[:power_oid.rindex(".")]
            db.add(new_switch)
            close_session(db)
            return json.dumps({ "switch": switch_data["name"] })
        else:
            return json.dumps({"check": checks})
    else:
        return json.dumps({"missing": missing_data })


@admin_v1.route("/switch/ports/<string:switch_name>", methods=["POST"])
@auth
def port_status(switch_name):
    status = get_poe_status(switch_name)
    result = { switch_name: [] }
    for port in range(0, len(status)):
        if status[port] == '1':
            result[switch_name].append('on')
        elif status[port] == '2':
            result[switch_name].append('off')
        else:
            result[switch_name].append('unknown')
    return json.dumps(result)


@admin_v1.route("/switch/nodes/<string:switch_name>", methods=["POST"])
@auth
def switch_nodes(switch_name):
    result = { "errors": [], "nodes": {}}
    db = open_session()
    sw = db.query(RaspSwitch).filter(RaspSwitch.name == switch_name).first()
    if sw.master_port > 0:
        result["nodes"][sw.master_port] = "pimaster"
    # Build the node information
    for n in db.query(RaspNode).filter(RaspNode.switch == sw.name).all():
        result["nodes"][str(n.port_number)] = n.name
    close_session(db)
    return json.dumps(result)


@admin_v1.route("/switch/turn_on/<string:switch_name>", methods=["POST"])
@auth
def turn_on(switch_name):
    if "ports" in flask.request.json:
        for port in flask.request.json["ports"]:
            turn_on_port(switch_name, port)
    return json.dumps({})


@admin_v1.route("/switch/turn_off/<string:switch_name>", methods=["POST"])
@auth
def turn_off(switch_name):
    result = {"errors": [] }
    if "ports" not in flask.request.json:
        result["errors"].append("Required parameters: 'ports'")
    db = open_session()
    sw = db.query(RaspSwitch).filter(RaspSwitch.name == switch_name).first()
    master_port = sw.master_port
    close_session(db)
    for port in flask.request.json["ports"]:
        if port == master_port:
            result["errors"].append("can not turn off the pimaster")
            logging.error("can not turn off the pimaster on the port  %s of the switch '%s'" % (
                port, switch_name))
        else:
            turn_off_port(switch_name, port)
    return json.dumps(result)


@admin_v1.route("/switch/init_detect/<string:switch_name>", methods=["POST"])
@auth
def init_detect(switch_name):
    result = { "errors": [], "network": "", "ip_offset": 0, "macs": [] }
    if "ports" not in flask.request.json:
        result["errors"].append("Required parameters: 'ports'")
        return json.dumps(result)
    # Get the network IP from the dnsmasq configuration
    cmd = "grep listen-address /etc/dnsmasq.conf"
    process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        universal_newlines=True)
    network_ip = process.stdout.split("=")[1]
    result["network"] = network_ip[:network_ip.rindex(".")]
    if len(result["network"].split(".")) != 3:
        logging.error("Wrong network IP from the dnsmasq configuration: %s" % result["network"])
        result["errors"].append("Wrong network IP from the dnsmasq configuration")
    # Get existing static IP from the dnsmasq configuration
    existing_ips = []
    existing_macs = []
    cmd = "grep ^dhcp-host /etc/dnsmasq.conf"
    process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        universal_newlines=True)
    for line in process.stdout.split('\n'):
        if "," in line and not line.startswith("#"):
            existing_ips.append(line.split(",")[2])
            existing_macs.append(line.split(",")[0][-17:])
            result["macs"].append(line.split(",")[0][-17:])
    logging.info("existing ips: %s" % existing_ips)
    logging.info("existing macs: %s" % existing_macs)
    # Check the node IP is available
    db = open_session()
    sw = db.query(RaspSwitch).filter(RaspSwitch.name == switch_name).first()
    ip_offset = sw.first_ip - 1
    close_session(db)
    result["ip_offset"] = ip_offset
    for port in flask.request.json["ports"]:
        node_ip = "%s.%d" % (result["network"], (ip_offset + int(port)))
        if  node_ip in existing_ips:
            result["errors"].append("%s already exists in the DHCP configuration!" % node_ip)
            return json.dumps(result)
    # Expose TFTP files to all nodes (boot from the NFS server)
    tftp_files = glob('/tftpboot/rpiboot_uboot/*')
    for f in tftp_files:
        if os.path.isdir(f):
            new_f = '/tftpboot/%s' % os.path.basename(f)
            if not os.path.isdir(new_f):
                shutil.copytree(f, new_f)
        else:
            shutil.copy(f, '/tftpboot/%s' % os.path.basename(f))
    return json.dumps(result)


@admin_v1.route("/switch/dhcp_conf/<string:switch_name>", methods=["POST"])
@auth
def dhcp_conf(switch_name):
    result = { "errors": [], "node_ip": "" }
    if "port" not in flask.request.json or "macs" not in flask.request.json or \
        "base_name" not in flask.request.json or \
        "network" not in flask.request.json or "ip_offset" not in flask.request.json:
        result["errors"].append("Required parameters: 'port', 'macs', 'network', 'base_name' and 'ip_offset'")
        return json.dumps(result)
    known_macs = flask.request.json["macs"]
    node_port = int(flask.request.json["port"])
    last_digit = int(flask.request.json["ip_offset"]) + node_port
    node_name = "%s-%d" % (flask.request.json["base_name"], last_digit)
    node_ip = "%s.%d" % (flask.request.json["network"], last_digit)
    # Detect MAC address by sniffing DHCP requests
    logging.info('Reading system logs to get failed DHCP requests')
    # Reading system logs to retrieve failed DHCP requests
    cmd = "grep -a DHCPDISCOVER /var/log/syslog | grep \"no address\" | tail -n 1"
    process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True)
    node_mac = ""
    for line in process.stdout.split('\n'):
        if len(line) > 0:
            now = datetime.now()
            # Hour with the format "%H:%M:%S"
            hour = line.split()[2].split(":")
            log_date = now.replace(hour = int(hour[0]), minute = int(hour[1]), second = int(hour[2]))
            logging.info("Last DHCP request at %s" % log_date)
            if (now - log_date).seconds < 20:
                mac = line.split()[7]
                if len(mac) == 17 and (mac.startswith("dc:a6:32") or mac.startswith("b8:27:eb")):
                    if mac in known_macs:
                        logging.error("[%s] MAC '%s' already exists in the DHCP configuration" % (node_name, mac))
                        result["errors"].append("%s already exists in the DHCP configuration!" % mac)
                        return json.dumps(result)
                    node_mac = mac
    if len(node_mac) > 0:
        logging.info("[%s] new node with the MAC '%s'" % (node_name, node_mac))
        # Configure the node IP according to the MAC address
        cmd = "echo 'dhcp-host=%s,%s,%s' >> /etc/dnsmasq.conf" % (node_mac, node_name, node_ip)
        process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("[%s] MAC: '%s', IP: '%s'" % (node_name, node_mac, node_ip))
        # Restart dnsmasq
        cmd = "service dnsmasq restart"
        process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Reboot the node
        turn_off_port(switch_name, node_port)
        time.sleep(1)
        turn_on_port(switch_name, node_port)
        # Fill the result
        result["node_ip"] = node_ip
    else:
        logging.warning("[%s] no detected MAC" % node_name)
    return json.dumps(result)


def delele_dhcp_ip(client_ip):
    cmd = "sed -i '/%s$/d' /etc/dnsmasq.conf" % client_ip
    process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = "service dnsmasq restart"
    process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    
def delele_dhcp_mac(client_mac):
    cmd = "sed -i '/%s/d' /etc/dnsmasq.conf" % client_mac
    process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = "service dnsmasq restart"
    process = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@admin_v1.route("/switch/dhcp_conf/<string:switch_name>/del", methods=["POST"])
@auth
def dhcp_conf_del(switch_name):
    result = { "errors": [] }
    flask_data = flask.request.json
    if "ip" not in flask_data or "mac" not in flask_data:
        result["errors"].append("Required parameters: 'ip' or 'mac'")
        return json.dumps(result)
    # Delete records in dnsmasq configuration using IP
    if len(flask_data["ip"]) > 0:
        delele_dhcp_ip(flask_data["ip"])
    # Delete records in dnsmasq configuration using MAC
    if len(flask_data["mac"]) > 0:
        delele_dhcp_mac(flask_data["mac"])
    return json.dumps(result)


@admin_v1.route("/switch/node_conf/<string:switch_name>", methods=["POST"])
@auth
def node_conf(switch_name):
    result = { "errors": [], "serial": "" }
    if "node_ip" not in flask.request.json or "port" not in flask.request.json \
        or "base_name" not in flask.request.json:
        result["errors"].append("Required parameters: 'node_ip', 'base_name', 'port'")
        return json.dumps(result)
    node_ip = flask.request.json["node_ip"]
    node_port = flask.request.json["port"]
    node_name = "%s-%s" % (flask.request.json["base_name"], node_ip.split(".")[-1])
    node_model = ""
    node_serial = ""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(node_ip, username="root", timeout=1.0)
        (stdin, stdout, stderr) = ssh.exec_command("cat /proc/cpuinfo")
        return_code = stdout.channel.recv_exit_status()
        for line in  stdout.readlines():
            output = line.strip()
            if "Revision" in output:
                rev = output.split()[-1]
                if rev == "a020d3":
                    node_model = "RPI3B+1G"
                if rev == "a03111":
                    node_model = "RPI4B1G"
                if rev in ["b03111", "b03112" , "b03114"]:
                    node_model = "RPI4B2G"
                if rev in ["c03111", "c03112" , "c03114"]:
                    node_model = "RPI4B4G"
                if rev == "d03114":
                    node_model = "RPI4B8G"
                if len(node_model) == 0:
                    node_model = "unknown"
            if "Serial" in output:
                node_serial = output.split()[-1][-8:]
                result["serial"] = node_serial
        ssh.close()
        # End of the configuration, turn off the node
        turn_off_port(switch_name, node_port)
        # Write the node information to the database
        if len(node_serial) > 0 and len(node_model) > 0:
            db = open_session()
            existing = db.query(RaspNode).filter(RaspNode.name == node_name).all()
            for to_del in existing:
                db.delete(to_del)
            new_node = RaspNode()
            new_node.name = node_name
            new_node.ip = node_ip
            new_node.switch = switch_name
            new_node.port_number = node_port
            new_node.model = node_model
            new_node.serial = node_serial
            db.add(new_node)
            close_session(db)
    except (AuthenticationException, SSHException, socket.error):
        logging.warn("[node-%s] can not connect via SSH to %s" % (node_port, node_ip))
    except:
        logging.exception("[node-%s] node configuration fails" % node_port)
    return json.dumps(result)


@admin_v1.route("/switch/clean_detect", methods=["POST"])
@auth
def clean_detect():
    result = { "errors": [] }
    # Delete the files in the tftpboot directory
    tftp_files = glob('/tftpboot/rpiboot_uboot/*')
    for f in tftp_files:
        new_f = f.replace('/rpiboot_uboot','')
        if os.path.isdir(new_f):
            shutil.rmtree(new_f)
        else:
            if not 'bootcode.bin' in new_f:
                os.remove(new_f)
    return json.dumps(result)


@admin_v1.route("/add/node", methods=["POST"])
@auth
def add_node():
    json_data = flask.request.json
    # Required properties to create Raspberry nodes
    node_props = [str(c).split(".")[1] for c in RaspNode.__table__.columns]
    missing_data = {}
    for prop in node_props:
        if prop not in json_data:
            # Create a missing prop without default values
            missing_data[prop] = []
            if prop == "switch":
                db = open_session()
                switches = db.query(distinct(RaspSwitch.name)).all()
                if len(switches) == 0:
                    missing_data[prop].append("no_values")
                else:
                    for sw in switches:
                        missing_data[prop].append(sw[0])
                close_session(db)
    # Check if all properties belong to the POST data
    if len(missing_data) == 0:
        db = open_session()
        existing = db.query(RaspNode).filter(RaspNode.name == json_data["name"]).all()
        for to_del in existing:
            db.delete(to_del)
        new_node = RaspNode()
        new_node.name = json_data["name"]
        new_node.ip = json_data["ip"]
        new_node.switch = json_data["switch"]
        new_node.port_number = json_data["port_number"]
        new_node.model = json_data["model"]
        new_node.serial = json_data["serial"]
        db.add(new_node)
        close_session(db)
        return json.dumps({ "node": json_data["name"] })
    else:
        return json.dumps({"missing": missing_data })


@admin_v1.route("/delete/<el_type>", methods=["POST"])
@auth
def delete(el_type):
    data = flask.request.json
    props = [ "name" ]
    # Check if all properties belong to the POST data
    missing_data = [key_data for key_data in props if key_data not in data.keys()]
    if len(missing_data) == 0:
        if el_type == "node":
            db = open_session()
            existing = db.query(RaspNode).filter(RaspNode.name == data["name"]).all()
            for to_del in existing:
                db.delete(to_del)
            close_session(db)
        elif el_type == "switch":
            db = open_session()
            existing = db.query(RaspSwitch).filter(RaspSwitch.name == data["name"]).all()
            for to_del in existing:
                db.delete(to_del)
            close_session(db)
        elif el_type == "environment":
            db = open_session()
            existing = db.query(RaspEnvironment).filter_by(name = data["name"]).all()
            for to_del in existing:
                db.delete(to_del)
            close_session(db)
        elif el_type == "client":
            # Delete a DHCP client (IP address is in the 'name' attribute)
            delele_dhcp_ip(data["name"])
            existing = [ data["name"] ]
        else:
            return json.dumps({"type_error": data["type"] })
        return json.dumps({ "delete": len(existing) })
    else:
        return json.dumps({"missing": missing_data })
