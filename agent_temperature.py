# Load the configuration file
from lib.config_loader import load_config, get_config
import sys

if len(sys.argv) != 2:
    print("The configuration file is required in parameter.")
    print("For example, 'python3 %s config.json'" % sys.argv[0])
    sys.exit(2)
load_config(sys.argv[1])

from database.connector import open_session, close_session
from database.tables import ActionProperty, RaspEnvironment, RaspNode, RaspSwitch, Schedule
from datetime import datetime
from influxdb import InfluxDBClient
from lib.switch_snmp import switch_cons
import logging, subprocess, time


logging.basicConfig(filename='info_temperature.log', level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

db = open_session()
influx = InfluxDBClient(host='localhost', port=8086)
influx_dbs = [info["name"] for info in influx.get_list_database()]
if "monitoring" not in influx_dbs:
    logging.warning("No 'monitoring' database. Create the 'monitoring' database")
    influx.create_database('monitoring')
influx.switch_database('monitoring')
logging.info("The temperature agent is running!")
while True:
    start_time = datetime.utcnow()
    record_time = datetime.utcnow().replace(microsecond=0)
    influx_points = []
    for node_info in db.query(Schedule, RaspNode, ActionProperty, RaspEnvironment
            ).filter(Schedule.action_state == "deployed"
            ).filter(Schedule.node_name == RaspNode.name 
            ).filter(ActionProperty.prop_name == "environment" 
            ).filter(ActionProperty.node_name == RaspNode.name 
            ).filter(RaspEnvironment.name == ActionProperty.prop_value 
            ).all():
        try:
            node = node_info[1]
            env = node_info[3]
            cmd = [
                "ssh", "-o StrictHostKeyChecking=no", "-o ConnectTimeout=2",
                "%s@%s"%(env.ssh_user, node.ip),
                "cat /sys/class/thermal/thermal_zone0/temp"
            ]
            process = subprocess.run(cmd, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, universal_newlines=True, timeout=10)
            temp_str = process.stdout.split()
            if len(temp_str) > 0 and len(temp_str[0]) > 4:
                influx_points.append({
                    "measurement": "temperature_C",
                    "time": record_time.isoformat(),
                    "tags": { "node": node_info[0].node_name },
                    "fields": {
                        "consumption": int(int(temp_str[0]) / 1000)
                    }
                })
        except:
            logging.exception("[%s] temperature failure" % node_info[0].node_name)
    if len(influx_points) > 0:
        influx.write_points(influx_points)
    diff_time = (record_time - start_time).total_seconds()
    if diff_time < 10:
        time.sleep(10 - diff_time)
close_session(db)
