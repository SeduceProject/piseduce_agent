# Load the configuration file
import sys
from lib.config_loader import load_config, get_config

if len(sys.argv) != 2:
    print("The configuration file is required in parameter.")
    print("For example, 'python3 %s config.json'" % sys.argv[0])
    sys.exit(2)
load_config(sys.argv[1])

from database.connector import open_session, close_session
from database.tables import RaspSwitch
from datetime import datetime
from influxdb import InfluxDBClient
from lib.switch_snmp import switch_cons
import logging, time


logging.basicConfig(filename='info_monitoring.log', level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

db = open_session()
influx = InfluxDBClient(host='localhost', port=8086)
influx_dbs = [info["name"] for info in influx.get_list_database()]
if "monitoring" not in influx_dbs:
    logging.warning("No 'monitoring' database. Create the 'monitoring' database")
    influx.create_database('monitoring')
influx.switch_database('monitoring')
logging.info("The monitoring agent is running!")
while True:
    start_time = datetime.utcnow()
    record_time = datetime.utcnow()
    try:
        for s in db.query(RaspSwitch).all():
            if len(s.power_oid) > 5:
                cons = switch_cons(s.ip, s.community, s.power_oid)
                influx_points = []
                record_time = datetime.utcnow().replace(microsecond=0).isoformat()
                for port, watt in enumerate(cons):
                    influx_points.append({
                        "measurement": "power_W",
                        "tags": {
                            "switch": s.name,
                            "port": port + 1
                        },
                        "time": record_time,
                        "fields": {
                            "consumption": watt
                        }
                    })
                influx.write_points(influx_points)
                # Update the record_time to compute the elapsed time between to sleep.time()
                record_time = datetime.utcnow()
    except:
        logging.exception("Can not get the switch consumptions")
    diff_time = (record_time - start_time).total_seconds()
    if diff_time < 10:
        time.sleep(10 - diff_time)
close_session(db)
