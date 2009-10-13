# -*- coding: utf-8 -*-
from zope.interface import implements
from twisted.internet import defer
from twisted.words.protocols.jabber.xmlstream import IQ
from twisted.words.protocols.jabber.jid import JID
from twisted.words.xish import xpath, domish

from wokkel.iwokkel import IDisco
from wokkel.xmppim import PresenceProtocol
from wokkel.data_form import Form,Field
from wokkel.pubsub import Item,  NS_PUBSUB_NODE_CONFIG

from pubsub import PubSubRequestWithConf

NS_XML = 'http://www.w3.org/XML/1998/namespace'
NS_COMMANDS = 'http://jabber.org/protocol/commands'
NS_ROSTER = 'jabber:iq:roster'
NS_ADMIN = 'http://jabber.org/protocol/admin'
CMD_ADMIN_USER_STATS = NS_ADMIN + '#user-stats'
NODE_ONLINE_USERS = 'online users'

PUB_NODE_LIVE = "presence/live" #node name where we publish items, not persitent, live flow
PUB_NODE_ACTUAL = "presence/actual" #node name where all subitems displays current presence status, persistent

class PublishPresence(PresenceProtocol):  
    implements(IDisco)
    
    def connectionInitialized(self):
        super(PublishPresence,self).connectionInitialized()
        self.create_nodes()
        self.make_uptodate()
        
    def create_nodes(self):
        """
        Creates and configures pubsub nodes
        
        TODO: add configuration process, do not rely on default one
        """
        def configure_node_live(data):
            request = PubSubRequestWithConf('configureSet')
            request.recipient = JID(self.pubsub_name)
            request.nodeIdentifier = PUB_NODE_LIVE
            request.sender = JID(self.name)
            
            frm = Form('submit')
            frm.addField( Field(fieldType='hidden',var='FORM_TYPE',value=NS_PUBSUB_NODE_CONFIG) )
            frm.addField( Field(var='pubsub#title',value='Live presence events') )
            frm.addField( Field(var='pubsub#persist_items',value='0') )
            frm.addField( Field(var='pubsub#deliver_payloads',value='1') )
            frm.addField( Field(var='pubsub#send_last_published_item',value='never') )
            frm.addField( Field(var='pubsub#presence_based_delivery',value='1') )
            request.configureForm = frm
                        
            request.send(self.xmlstream)
            
        def configure_node_actual(data):
            request = PubSubRequestWithConf('configureSet')
            request.recipient = JID(self.pubsub_name)
            request.nodeIdentifier = PUB_NODE_ACTUAL
            request.sender = JID(self.name)
            
            frm = Form('submit')
            frm.addField( Field(fieldType='hidden',var='FORM_TYPE',value=NS_PUBSUB_NODE_CONFIG) )
            frm.addField( Field(var='pubsub#title',value='Live presence events') )
            frm.addField( Field(var='pubsub#persist_items',value='1') )
            frm.addField( Field(var='pubsub#deliver_payloads',value='1') )
            frm.addField( Field(var='pubsub#send_last_published_item',value='never') )
            frm.addField( Field(var='pubsub#presence_based_delivery',value='1') )
            request.configureForm = frm
            request.send(self.xmlstream)
        
        d = self.pubsub_client.createNode(JID(self.pubsub_name), PUB_NODE_LIVE, sender=JID(self.name))
        d.addBoth(configure_node_live)
        
        d = self.pubsub_client.createNode(JID(self.pubsub_name), PUB_NODE_ACTUAL, sender=JID(self.name))
        d.addBoth(configure_node_actual)
    
    def make_uptodate(self):
        """
        Fetches current logged users from server, currently published items and synchronizes them
        
        NOT WORKS YET
        """
        return
        
        def process_online_users(items):
            #FIXME: if users has multiple connections we should handle it
            res['online'] = set( user.entity.userhost() for user in items )
            if 'online' in res and 'published' in res:
                do_sync(res)
            
        def process_published_items(items):
            published_users = dict()
            for item in items:
                #TODO: serializing and deserializing should take place in separate func
                pub_user = item.children[0]['name']
                user = dict( name = pub_user['name'],
                      ip = pub_user['ip'],
                      fulljid = pub_user['fulljid'],
                      status = pub_user['status'] )
                published_users[pub_user['name']] = user
                    
            res['published'] = published_users
            if 'online' in res and 'published' in res:
                do_sync(res)
                
        def do_sync(resdict):
            online = resdict['online']
            published_users = resdict['published']            

        res = dict()
        
        d = self.disco_client.requestItems(JID(self.domain),NODE_ONLINE_USERS, sender=JID(self.name))
        d.addCallback(process_online_users)
        d = self.pubsub_client.items(JID(self.pubsub_name),PUB_NODE_ACTUAL, sender=JID(self.name))
        d.addCallback(process_published_items)
        
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
        
        TODO: handle situations when multiple connections with multiple resources
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
        """
        
        def process_newpresence(userstats):
            """
            publish new payload
            """
            
            #make new item which would be published
            #TODO: serializing and deserializing should take place in separate func
            payload = domish.Element((None,"user"))
            for k,v in userstats.items():
                payload[k] = v
            payload['status'] = status
            
            item = Item(payload=payload)
            
            #actually publish item
            self.pubsub_client.publish(JID("pubsub.%s"%domain),PUB_NODE_LIVE,items=[item],sender=JID(comp_name))
            
        d = self.get_userstats(user,comp_name,domain)
        d.addCallback(process_newpresence)
        
    
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
            userstats['name'] = jid.userhost()
            userstats['fulljid'] = jid.full() #full jid which causes current change, i.e. which is user actualy uses
            userstats['ip'] = ip
            return userstats
        
    
        #TODO: implement error handling if ACL doesn't allows us to call admin command
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
