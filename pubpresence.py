# -*- coding: utf-8 -*-
from zope.interface import implements
from twisted.internet import defer
from twisted.names import client
from twisted.words.protocols.jabber.xmlstream import IQ
from twisted.words.protocols.jabber.jid import JID
from twisted.words.xish import xpath, domish

from wokkel.iwokkel import IDisco
from wokkel.xmppim import PresenceProtocol, ProbePresence
from wokkel.data_form import Form,Field
from wokkel.pubsub import Item,  NS_PUBSUB_NODE_CONFIG

from pubsub import PubSubRequestWithConf

NS_XML = 'http://www.w3.org/XML/1998/namespace'
NS_COMMANDS = 'http://jabber.org/protocol/commands'
NS_ROSTER = 'jabber:iq:roster'
NS_ADMIN = 'http://jabber.org/protocol/admin'
CMD_ADMIN_USER_STATS = NS_ADMIN + '#user-stats'
NODE_ONLINE_USERS = 'online users'

PUB_NODE = "/pubpresence" #node name where all subitems displays current presence status, persistent

class PublishPresence(PresenceProtocol):  
    implements(IDisco)
    
    dns_client = client.Resolver('/etc/resolv.conf')
    
    def connectionInitialized(self):
        super(PublishPresence,self).connectionInitialized()
        self.create_nodes()
        self.initial_publish()
                
    def create_nodes(self):
        """
        Creates and configures pubsub nodes
        
        TODO: configure security model
        """            
        def configure_node(data):
            request = PubSubRequestWithConf('configureSet')
            request.recipient = JID(self.pubsub_name)
            request.nodeIdentifier = PUB_NODE
            request.sender = JID(self.name)
            
            frm = Form('submit')
            frm.addField( Field(fieldType='hidden',var='FORM_TYPE',value=NS_PUBSUB_NODE_CONFIG) )
            frm.addField( Field(var='pubsub#title',value='Live presence events') )
            frm.addField( Field(var='pubsub#persist_items',value='1') )
            frm.addField( Field(var='pubsub#deliver_payloads',value='1') )
            frm.addField( Field(var='pubsub#send_last_published_item',value='never') )
            frm.addField( Field(var='pubsub#presence_based_delivery',value='0') )
            frm.addField( Field(var='pubsub#access_model',value='open') )
            frm.addField( Field(var='pubsub#node_type',value='leaf') )
            request.configureForm = frm
            request.send(self.xmlstream)

        d = self.pubsub_client.createNode(JID(self.pubsub_name), PUB_NODE, sender=JID(self.name))
        #if node is exist it's possible that we'll need to configure it anyway
        d.addBoth(configure_node)
        
    def initial_publish(self):
        """
        purges currently published items on persistent node, then asks all users to send presence data again
        """
        
        def process_online_users(items):
            for user in items:
                self.probe(user.entity,sender=JID(self.name))

        #purge all published items under persistent node
        #client to this node will be notified about node purge
        request = PubSubRequestWithConf('purge')
        request.recipient = JID(self.pubsub_name)
        request.nodeIdentifier = PUB_NODE
        request.sender = JID(self.name)
        d = request.send(self.xmlstream)

        d = self.disco_client.requestItems(JID(self.domain),NODE_ONLINE_USERS, sender=JID(self.name))
        d.addCallback(process_online_users)

        
    def getDiscoInfo(self, requestor, target, nodeIdentifier=''):
        return defer.succeed([])

    def getDiscoItems(self, requestor, target, node):
        return defer.succeed([])
        
    def subscribeReceived(self, presence):     
        user,component = self._getParts(presence)
        self.subscribed(user,sender=component)
        self.available(user,sender=component)
        self.subscribe(user,sender=component)
        
    def unsubscribeReceived(self, presence):
        user,component = self._getParts(presence)
        self.unsubscribed(user,sender=component)

    def probeReceived(self, presence):
        user,component = self._getParts(presence)            
        self.available(user,sender=component)
        
    def availableReceived(self, presence, show=None, statuses=None, priority=0):
        """
        We have received presence from user, get it's IP and publish new info
        
        publish format is <user name=jid ip=ip_addr status=status />
        where status could be:
            - online - plain online
            - dnd - do nod distrib
            - away - away
            - xa - really away
            - chat - ready for chat
        
        TODO: handle situations when multiple connections of same user exist, 
              non-away connections should have higher priority
        """
        user = presence.sender
        comp_name = presence.recipient.userhost()
        domain = user.host
        
        status = presence.show or 'online'
        self.presenceChanged(user,comp_name,domain,status)
        
    def unavailableReceived(self, presence):
        
        user = presence.sender
        comp_name = presence.recipient.userhost()
        domain = user.host
        status = 'offline'
        self.presenceChanged(user,comp_name,domain,status)
        
    def presenceChanged(self,user,comp_name,domain,status):
        """
        Processs change of presence of user

        It publshes items or pubsub node which should be persistent
        Every item is published with id == username (jid without resource)
        this means, that in case if update node will be atomaticaly
        replaced with new value, no need to delete and recreate node
        """
        
        def process_dns(dnsresult,userstats):
            try:
                hostname = str(dnsresult[0][0].payload.name)
            except:
                #DNS error happens, publish empty hostname
                hostname = ""

            username = userstats['username']
            userstats['hostname'] = hostname
            #make new item which would be published
            #TODO: serializing and deserializing should take place in separate func
            payload = domish.Element((None,"user"))
            for k,v in userstats.items():
                payload[k] = v
                
            item = Item(id=username,payload=payload)
            self.pubsub_client.publish(JID("pubsub.%s"%self.domain),PUB_NODE,items=[item],sender=JID(self.name))
                       
        def process_newpresence(userstats,status):
            """
            publish new payload
            """            
            userstats['status'] = status
            username = userstats['username']

            #delete node if offline, resolve hostname add publish node otherwise
            if status == 'offline':
                request = PubSubRequestWithConf('retract')
                request.recipient = JID(self.pubsub_name)
                request.nodeIdentifier = PUB_NODE
                request.sender = JID(self.name)
                request.itemIdentifiers = [username]
                request.send(self.xmlstream)
            else:            
                #build reverse ip name for DNS query
                reverse_ip = '.'.join(userstats['ip'].split('.')[::-1])+'.in-addr.arpa.'
                d = self.dns_client.lookupPointer(reverse_ip)
                d.addBoth(process_dns,userstats)
        
        d = self.get_userstats(user,comp_name,domain)
        d.addCallback(process_newpresence,status)
        return d
        
    
    def get_userstats(self,user,comp_name,domain):
        """
        Get stats of user. Accepts params:
        
        user - user jid
        comp_name - component name which should receive answer (usually we are)
        domain - our domain
        
        returns callback with one cb added - it converts answer to dict with fields name,fulljid,ip,status
        """
    
        def process_stats(item):
            """
            Process result of user-stats command
            
            Extract IP address and related info and returns it as dict
            """
            x = xpath.queryForNodes("//x/field[@var='ipaddresses']",item)
            if not x:
                raise ValueError, "Wrong response from stats-request"
                
            frm = Form.fromElement(x[0])
            values = frm.getValues()
            jid = JID(values['accountjid'])
            ipport = values['ipaddresses']
            
            ip, port = ipport.split(':')

            userstats = dict()
            userstats['username'] = jid.userhost()
            userstats['fulljid'] = jid.full() #full jid which causes current change, i.e. which is connestion actualy used
            userstats['ip'] = ip
            return userstats
    
        #TODO: implement error handling if ACL doesn't allows us to call admin commands
        iq = IQ(self.xmlstream)
        iq['to'] = domain
        iq['from'] = comp_name
        cmd = iq.addElement((NS_COMMANDS,'command'))
        cmd['node'] = CMD_ADMIN_USER_STATS
       
        frm = Form('submit')
        frm.addField( Field(fieldType='hidden',var='FORM_TYPE',value=NS_ADMIN) )
        frm.addField( Field(fieldType='jid-single',var='accountjid',value=user.full()) )
        cmd.addChild(frm.toElement())
        d = iq.send(domain)
        d.addCallback(process_stats)
        return d
        
    def _getParts(self,presence):
        return presence.sender,presence.recipient
