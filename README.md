## PiSeduce Project

The PiSeduce Resource Manager is a Python reservation tool that manages Raspberry Pi 3 and Pi 4.
This software allows users to reserve Raspberrys and deploy preconfigured environments on their
boards. The reservations have limited duration in order to share the resources available.
Environments are Raspberry operating systems customized to meet the user requirements, for example,
using a Web IDE as Cloud9. Currently, there are three proposed operating systems: Raspbian OS,
Ubuntu and piCore (or tinyCore), a minimalist operating system.

Raspberrys before the Raspberry Pi 3 can not be used with our resource manager because they do not
implement the PXE boot process. This network boot allows the manager to choose the OS to boot on the
Raspberrys.

The PiSeduce resource manager consists of two projects: the
[piseduce_webui](https://github.com/SeduceProject/piseduce_webui) project and the
[piseduce_agent](https://github.com/SeduceProject/piseduce_agent) project. These both projects are hosted
on GitHub.

The **piseduce_webui** project is the web interface of the resource manager. It also manages the
user accounts to secure access to the resource manager.

The **piseduce_agent** project manages the user reservations and the resources of the
infrastructure, e.g., the Raspberrys. To manage the Raspberrys, the agent can connect to them via
SSH connections.

[Read More](https://doc.seduce.fr/2021-07-22-manager-basis/)
