from database.base import Base
from sqlalchemy import Boolean, Column, Integer, String, Text


class Node(Base):
    __tablename__ = 'node'
    type = Column(Text)
    name = Column(Text, primary_key=True)
    ip = Column(Text)
    owner = Column(Text)
    bin = Column(Text)
    status = Column(Text)
    lost_state = Column(Text)
    start_date = Column(Text)
    duration = Column(Integer)


    def __repr__(self):
        return "Node(%s, %s, %s)" % (self.name, self.status, self.owner)


class NodeProperty(Base):
    __tablename__ = 'node_prop'
    uid = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text)
    prop_name = Column(Text)
    prop_value = Column(Text)


class Switch(Base):
    __tablename__ = 'switch'
    uid = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text)
    prop_name = Column(Text)
    prop_value = Column(Text)


class Environment(Base):
    __tablename__ = 'environment'
    uid = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text)
    prop_name = Column(Text)
    prop_value = Column(Text)


class Action(Base):
    __tablename__ = 'action'
    uid = Column(Integer, primary_key=True, autoincrement=True)
    node_name = Column(Text)
    node_ip = Column(Text)
    environment = Column(Text)
    process = Column(Text)
    state = Column(String(120))
    state_idx = Column(Integer)
    reboot_state = Column(String(120))
    updated_at = Column(Text)


    def __repr__(self):
        return "action(%s, %s, %s)" % (self.node_name, self.state, self.updated_at)


class ActionProperty(Base):
    __tablename__ = 'action_prop'
    uid = Column(Integer, primary_key=True, autoincrement=True)
    node_name = Column(Text)
    prop_name = Column(Text)
    prop_value = Column(Text)


