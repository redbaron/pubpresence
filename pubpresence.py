# -*- coding: utf-8 -*-
from zope.interface import implements
from twisted.internet import defer
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

PUB_NODE_LIVE = "presence/live" #node name where we publish items, not persitent, live flow
PUB_NODE_ACTUAL = "presence/actual" #node name where all subitems displays current presence status, persistent
PUB_NODE_STATUS = "presence/status" #node name we publish our status, like "initializing" or "online"

class PublishPresence(PresenceProtocol):  
    implements(IDisco)
    
    online = False
    def __init__(self):
        super(PublishPresence,self).__init__()
        self.pending_init = set()
        self.published_items = dict() #we store here publshed persist items
        
    
    def connectionInitialized(self):
        super(PublishPresence,self).connectionInitialized()
        self.create_nodes()
        self.announce_init() #publish initialazing event
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

        def configure_node_status(data):
            request = PubSubRequestWithConf('configureSet')
            request.recipient = JID(self.pubsub_name)
            request.nodeIdentifier = PUB_NODE_STATUS
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


        d = self.pubsub_client.createNode(JID(self.pubsub_name), PUB_NODE_LIVE, sender=JID(self.name))
        d.addBoth(configure_node_live)
        
        d = self.pubsub_client.createNode(JID(self.pubsub_name), PUB_NODE_ACTUAL, sender=JID(self.name))
        d.addBoth(configure_node_actual)

        d = self.pubsub_client.createNode(JID(self.pubsub_name), PUB_NODE_STATUS, sender=JID(self.name))
        d.addBoth(configure_node_status)
        
    def announce_init(self):
        self.online = False
        
        frm = Form('result')
        frm.addField( Field(var='pubpresence#status',value='init') )
        item = Item(payload=frm.toElement())
        self.pubsub_client.publish(JID("pubsub.%s"%self.domain),PUB_NODE_STATUS,items=[item],sender=JID(self.name))

        
    def announce_online(self):
        self.online = True

        frm = Form('result')
        frm.addField( Field(var='pubpresence#status',value='online') )
        item = Item(payload=frm.toElement())
        self.pubsub_client.publish(JID("pubsub.%s"%self.domain),PUB_NODE_STATUS,items=[item],sender=JID(self.name))
   
    def announce_online_when_ready(self,result):
        if not self.pending_init:
            self.announce_online()

    def make_uptodate(self):
        """
        purges currently published items on persistent node, then asks all users to send presence data again
        """
        
        def process_online_users(items):
            for user in items:
                self.probe(user.entity,sender=JID(self.name))
                #we add all users which we ask for presence to get know 
                #later when initializaton is finished
                self.pending_init.add(user.entity.full()) 

        #purge all published items under persistent node
        request = PubSubRequestWithConf('purge')
        request.recipient = JID(self.pubsub_name)
        request.nodeIdentifier = PUB_NODE_ACTUAL
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
        if self.online:
            show=None
        else:
            show='dnd'
            
        self.available(user,show=show,sender=component)
        
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

            
        if not self.online:
            try:
                self.pending_init.remove(presence.sender.full())
            except KeyError:
                #FIXME: we probably somehere out of sync
                pass
            
        user = presence.sender
        comp_name = presence.recipient.userhost()
        domain = user.host
        
        status = presence.show or 'online'
        d = self.presenceChanged(user,comp_name,domain,status)
        
        if not self.online and not self.pending_init:
            d.addCallback(self.announce_online_when_ready)
        
    def unavailableReceived(self, presence):
        
        if not self.online:
            try:
                self.pending_init.remove(presence.sender.full())
            except KeyError:
                #FIXME: we probably somehere out of sync
                pass

        user = presence.sender
        comp_name = presence.recipient.userhost()
        domain = user.host
        status = 'offline'
        d = self.presenceChanged(user,comp_name,domain,status)
        
        if not self.online and not self.pending_init:
            # user is goes out during our init process
            d.addCallback(self.announce_online_when_ready)

    def presenceChanged(self,user,comp_name,domain,status):
        """
        Processs change of presence of user
        
        It publishes new event on "live" and "actual" node. If there was 
        previously published item for same user then it first remove it.
        If client app will connect and request "actual" list right before new item
        published, but after old one was removed, then it'll get this event anyway from
        live node. For that purposes it first do nesessary steps on "actual" node and
        only when finish there it publish item on "live" node
        """
        
        def store_persist(iq):
            """
            We store just published persist event ID here, to be able unpublish it when user goes offline
            """
            item = xpath.queryForNodes("//item",iq)
            if not item:
                return
            item = item[0]['id']
            name = user.userhost()
            self.published_items[name] = item
        
        def process_newpresence(userstats):
            """
            publish new payload
            """
            
            #delete previously published item if there was any
            if userstats['name'] in self.published_items:
                delreq = PubSubRequestWithConf('retract')
                delreq.recipient = JID(self.pubsub_name)
                delreq.nodeIdentifier = PUB_NODE_ACTUAL
                delreq.sender = JID(self.name)
                delreq.itemIdentifiers = [self.published_items[userstats['name']]]
                delreq.send(self.xmlstream)

            #make new item which would be published
            #TODO: serializing and deserializing should take place in separate func
            payload = domish.Element((None,"user"))
            for k,v in userstats.items():
                payload[k] = v
            payload['status'] = status
                        
            item = Item(payload=payload)

            #actually publish item on both nodes if not offline, otherwise publish only on "live" node
            if status != 'offline':
                d = self.pubsub_client.publish(JID("pubsub.%s"%self.domain),PUB_NODE_ACTUAL,items=[item],sender=JID(self.name))
                d.addCallback(store_persist) #on callback we'll receive ID of published item
            else:
                try:
                    del self.published_items[userstats['name']]
                except KeyError:
                    pass #Something wrong, we out of sync somewhere
                    
            self.pubsub_client.publish(JID("pubsub.%s"%self.domain),PUB_NODE_LIVE,items=[item],sender=JID(self.name))
                        
        d = self.get_userstats(user,comp_name,domain)
        d.addCallback(process_newpresence)
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
            userstats['name'] = jid.userhost()
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
