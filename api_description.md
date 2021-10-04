### /v1/user/*
The full documentation is available in the sources at
[user_v1.py](api/user_v1.py). All requests are POST requests.
* /v1/user/client/list: Retrieve the list of the DHCP clients read from the
  '/etc/dnsmasq.conf' file.
* /v1/user/switch/list: Retrieve the list of the managed switches
* /v1/user/switch/consumption: Retrieve the power consumption of the ports of
  the switch from the Influx DB.
* /v1/user/environment/register: Register to the database the environment that
  belongs to the Raspberry specified in the parameters.
* /v1/user/environment/list: Retrieve the list of the node environments.
* /v1/user/node/temperature: Retrieve the power consumption of the ports of
  the switch from the Influx DB.
* /v1/user/node/state: Retrieve the state of the nodes and other properties to
  display on the manage page.
* /v1/user/node/schedule: Return the list of node reservations.
* /v1/user/node/list: Retrieve the list of nodes with their properties.
* /v1/user/node/mine: Retrieve the list of deployment states and the list of
  nodes that are deploying for a specific user.
* /v1/user/reserve: Reserve the nodes selected by the user filters.
* /v1/user/configure: Retrieve the nodes in the 'configuring' state and the
  properties to provide to configure the nodes.
* /v1/user/deploy: Set the deployment properties of the nodes. After this
  operation, nodes are in the 'ready' state.
* /v1/user/destroy: Destroy the reservation associated to the nodes.
* /v1/user/hardreboot: Hard reboot (turn off then turn on) the nodes.
* /v1/user/bootfiles: Upload the boot files of the deployed nodes (/boot
  directory) to the TFTP server.
* /v1/user/deployagain: Deploy again the nodes.
* /v1/user/extend: Extend the node reservations by postponing the end date to a
  later date.

### /v1/admin/*
The code for these URLs are in [admin_v1.py](api/admin_v1.py). All requests are
POST requests.
* /v1/admin/node/pimaster: Retrieve the agent IP
* /v1/admin/pimaster/changeip: Change the agent IP and reconfigure the DHCP
  server.
* /v1/admin/node/rename: Rename the nodes from a basename. The new node names
  will be the basename followed by the switch port number.
* /v1/admin/add/environment: Add a new environment to the database.
* /v1/admin/add/client: Add a new DHCP client to the `/etc/dnsmasq.conf` file
  and restart the DHCP server.
* /v1/admin/add/switch: Add a new switch to the database. The IP and the SNMP
  configuration will be tested before modifying the database.
* /v1/admin/switch/ports/<switch_name>: Retrieve the PoE status (on or off) of
  all ports of the switch named `switch_name`.
* /v1/admin/switch/nodes/<switch_name>: Retrieve the nodes connected to the
  switch named `switch_name`.
* /v1/admin/switch/turn_on/<switch_name>: Turn on the port in the POST
  parameters of the switch named `switch_name`.
* /v1/admin/switch/turn_off/<switch_name>: Turn off the port in the POST
  parameters of the switch named `switch_name`.
* /v1/admin/init_detect/<switch_name>: Start the detection of the node on the
  port in the POST parameters. If the detection is completed, the node will be
  added to the database.
* /v1/admin/switch/dhcp_conf/<switch_name>: Configure the DHCP server for the
  node in the port specified in the POST parameters. The MAC address is
  retrieved by reading the system logs.
* /v1/admin/switch/dhcp_conf/<switch_name>/del: Delete the line in the
  `/etc/dnsmasq.conf` file associated to the node.
* /v1/admin/switch/node_conf/<switch_name>: Retrieve the Raspberry model and the
  Raspberry serial from SSH connections.
* /v1/admin/switch/clean_detect: Clean the TFTP boot server.
* /v1/admin/add/node: Add a new node to the database.
* /v1/admin/delete/<el_type>: Delete an element from the database. The element
  is found from the `el_type` (node, switch, environment, client) and the name
  speficied in the POST parameters. the client `el_type` is a DHCP client. So,
  the line associated to the DHCP client is deleted and the DHCP server is
  restarted.

### /v1/debug/*
The code for these URLs are in [debug_v1.py](api/debug_v1.py).
* [GET] /v1/debug/state: Return the type of the agent that is defined by the
  `node_type` property of the `config_agent.json` file.
* [POST] /v1/debug/auth: Test the authentication of the agent client by
  sending the token to the agent. The token sent must be the same as the token
  defined by the property `auth_token` in the configuration file.
