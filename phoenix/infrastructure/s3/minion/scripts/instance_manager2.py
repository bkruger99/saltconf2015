#!/usr/bin/env python
import sys
import time
import datetime 
import logging
import boto
import boto.sqs
from dynamodb_mapper.model import utc_tz, DynamoDBModel
import ddb
from ddb import MinionInstance
from ddb import MasterInstance
from msg2 import Msg
from sqs2 import Sqs
from key_manager import KeyManager
from helper2 import Helper


POLL_CYCLE = 15 # seconds to sleep between polling dynamodb for list of active salt masters
MASTERS_TABLE_NAME = "masters"
MINIONS_TABLE_NAME = "minions"
MASTER_QUEUE = "SqsMaster"
MINION_QUEUE = "SqsMinion"


class MasterManager:                                                                                                    
    def __init__(self, region):
        self.region = region
        ddb.set_region(self.region)

    def create_or_update_master(self, instanceid, modified, ipaddr, status):
        '''Attempt to retrieve the item update and save it, failing that create it and save it'''
        # no default value for instanceid, has be supplied
        if not instanceid:
            raise
        try:
            r = ddb.MasterInstance.get(instanceid)
            print "Master entry exists for instanceid %s" % instanceid
            if modified:
                r.modified = modified
            if ipaddr:
                r.ipaddr = unicode(ipaddr)
            if status:
                r.status = unicode(status)
            r.save(raise_on_conflict=True)
        #except ConflictError:  --- add this in later, design saves us from issue for now
        #    # giving a second try to save the data
        #    time.sleep(2)
        #    self.create_or_update_master(instanceid, modified, ipaddr, status)

        except boto.exception.BotoClientError:
            print "Minion entry does not exist for instanceid %s, creating one." % instanceid
            mm = MasterInstance()
            mm.instanceid = instanceid
            if modified:
                mm.modified = modified
            if ipaddr:
                mm.ipaddr = unicode(ipaddr)
            if status:
                mm.status = unicode(status)
            mm.save()
        except Exception, e:
            print "unhandled exception: %s" % e
            raise
        return

    def get_terminated(self):
        pass

class MinionManager:                                                                                                    
    def __init__(self, region):
        self.region = region
        ddb.set_region(self.region)

    def create_or_update_minion(self, instanceid, modified, highstate_runner, highstate_ran, status):
        '''Attempt to retrieve the item update and save it, failing that create it and save it'''
        # no default value for instanceid, has be supplied
        if not instanceid:
            raise
        try:
            r = ddb.MinionInstance.get(instanceid)
            print "Minion entry exists for instanceid %s" % instanceid
            if modified:
                r.modified = modified
            if highstate_runner:
                r.highstate_runner = highstate_runner
            if highstate_ran:
                r.highstate_ran = highstate_ran
            if status:
                r.status = status
            r.save(raise_on_conflict=True)
        #except ConflictError:  --- Must fix this for race condition of running highstates
        #    # giving a second try to save the data
        #    time.sleep(2)
        #    self.create_or_update_minion.....(instanceid, modified, ipaddr, status)

        except boto.exception.BotoClientError:
            print "Minion entry does not exist for instanceid %s, creating one." % instanceid
            mm = MinionInstance()
            mm.instanceid = instanceid
            if modified:
                mm.modified = modified
            if highstate_runner:
                mm.highstate_runner = highstate_runner
            if highstate_ran:
                mm.highstate_ran = highstate_ran
            if status:
                mm.status = status
            mm.save()
        except Exception, e:
            raise
        return

    def get_terminated(self):
        '''Scan the dynamodb table for all minions with status == terminated, return list'''
        mm = MinionInstance()
        terminated_minions = []
        try:
            minions = mm.scan()
            for m in minions:
                if m.status == 'TERMINATE':
                    terminated_minions.append(str(m.instanceid))
        except Exception, e:
            raise
        return terminated_minions

''' # Remove minion keys from my local salt master if their status is not active in dynamodb
    def terminate_minion(self, instanceid):
        pass
'''

def main():
    # getting local info from ha-config file
    try:
        h = Helper()
        region = h.get_region()
        instanceid = h.get_instanceid()
        ipaddr = h.get_private_ip()
        master_queue = h.get_master_queue_name()
        minion_queue = h.get_minion_queue_name()
        master_table = h.get_master_table_name() 
        minion_table = h.get_minion_table_name()
        print "region: %s" % region
        print "instanceid: %s" % instanceid
        print "ipaddr: %s" % ipaddr
        print "master_queue: %s" % master_queue
        print "minion_queue: %s" % minion_queue
        print "master_table: %s" % master_table
        print "minion_table: %s" % minion_table
    except Exception, e:
        print "Error when looking up data in ha-config: %s" % e
        raise

    # this salt master updates info about itself into dynamodb
    try:
        modified = datetime.datetime.now(utc_tz)
        local_master = MasterManager(region)
        local_master.create_or_update_master(instanceid=instanceid, modified=modified,
                                             ipaddr=ipaddr, status=u'LAUNCH' )
    except Exception, e:
        raise

    # Need sqs instances
    try:
        sqs_master = Sqs(boto.sqs.connect_to_region(region), master_queue)
        sqs_minion = Sqs(boto.sqs.connect_to_region(region), minion_queue)
    except Exception, e:
        raise

    # This is the endless loop of goodness
    while True:
        try:
            master_queue_length = sqs_master.get_queue_length()
            if master_queue_length > 0:
                for i in range(master_queue_length):
                    message = sqs_master.get_a_message() 
                    if not message:
                        continue
                    print "type of message is: %s" % type(message)
                    message_body = message.get_body() # using boto sqs message method here
                    print "message body:"
                    print message_body
                    msg = Msg(message_body)
                    instance_id = msg.get_instance_id()
                    print "instance_id: %s" % instance_id
                    status = msg.get_instance_action() # LAUNCH or TERMINATE or None
                    print "status: %s" % status
                    if not status or not instance_id:
                        print "status: %s" % status
                        print "instance_id: %s" % instance_id
                        continue
                    else:
                        print "region right before function is: %s" % region
                        master_mgr = MasterManager(region)
                        master_mgr.create_or_update_master(instanceid, modified=None, ipaddr=None, status=unicode(status))
                        print "region in function is: %s" % region
                        minion_mgr = MinionManager(region)
                        minion_mgr.create_or_update_minion(instanceid, modified=None, highstate_runner=None,
                                                           highstate_ran=None, status=unicode(status))
                        print "region right after function is: %s" % region
                    #msg.delete_a_message(message)
        except Exception, e:
            print "oops: %s" % e
        break    
   
       
    # BIG LOOP
        # poll masters sqs queue
        # update dynamodb master table
        # update dynamodb minion table with master entry
        # poll minion sqs queue
        # update minion dynamodb table
        # retrieve terminated minions from dynamodb table, and remove their salt keys from local master
        # sleep the poll cycle time

  


if __name__ == "__main__":
    try:
        main()
    except Exception, e:
        print "Problem occurred.   %s" % e
