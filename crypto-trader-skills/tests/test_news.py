import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from threading import Event

from crypto_skills import news
from crypto_skills.core import Workspace, SkillError

NOW='2026-11-17T12:03:00+00:00'
URL='https://feeds.example.org/rss'
RSS=b'<rss><channel><item><guid>one</guid><title>Bitcoin update</title><link>https://example.org/news/1</link><pubDate>Tue, 17 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>'


class NewsTests(unittest.TestCase):
    def setup_workspace(self,t):
        w=Workspace(t); w.write('config',dict(mode='paper',source_urls=[URL],source_min_interval_seconds=60)); return w

    def args(self,t,**kw):
        return SimpleNamespace(workspace=t,input=kw.get('input'),fetch=not kw.get('input'),now=kw.get('now',NOW))

    def test_private_credential_and_non_http_sources_rejected(self):
        for url in ['http://127.0.0.1/rss','http://[::1]/rss','https://u:p@example.org/rss',
                    'file:///etc/passwd','http://169.254.169.254/latest']:
            with self.subTest(url=url),self.assertRaises(SkillError): news.validate_url(url)
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.2',443))]):
            with self.assertRaises(SkillError): news.validate_url(URL,resolve=True)

    def test_malformed_source_config_has_skill_error(self):
        with tempfile.TemporaryDirectory() as t:
            w=self.setup_workspace(t)
            w.write('config',dict(mode='paper',source_urls=[{}],source_min_interval_seconds=60))
            with self.assertRaises(SkillError): news.run(self.args(t))

    def test_rss_poll_deduplicates_and_respects_interval(self):
        with tempfile.TemporaryDirectory() as t:
            self.setup_workspace(t)
            with patch.object(news,'_request',return_value=(200,{'etag':'abc'},RSS)):
                a=news.run(self.args(t))
            self.assertEqual(len(a['data']['items']),1)
            with patch.object(news,'_request',side_effect=AssertionError('polled too soon')):
                b=news.run(self.args(t,now='2026-11-17T12:03:30+00:00'))
            self.assertEqual(len(b['data']['items']),1)
            self.assertEqual(b['data']['source_health'][URL]['status'],'rate_limited')

    def test_import_updates_same_id_and_retains_version_history(self):
        with tempfile.TemporaryDirectory() as t:
            w=self.setup_workspace(t); p=Path(t)/'input.json'
            item=dict(id='x',title='First',url='https://example.org/x',source='manual',assets=['BTC'])
            p.write_text(json.dumps(dict(items=[item,item])))
            a=news.run(self.args(t,input=str(p)))
            self.assertEqual(len(a['data']['items']),1)
            item['title']='Corrected'; p.write_text(json.dumps(dict(items=[item])))
            b=news.run(self.args(t,input=str(p)))
            self.assertEqual(b['data']['items'][0]['title'],'Corrected')
            self.assertEqual(len(b['data']['items'][0]['versions']),2)
            item['title']='First'; p.write_text(json.dumps(dict(items=[item])))
            c=news.run(self.args(t,input=str(p)))
            self.assertEqual(c['data']['items'][0]['title'],'Corrected')

    def test_poll_failure_and_304_keep_items_but_report_source_health(self):
        with tempfile.TemporaryDirectory() as t:
            self.setup_workspace(t)
            with patch.object(news,'_request',return_value=(200,{},RSS)): news.run(self.args(t))
            with patch.object(news,'_request',return_value=(304,{},b'')):
                a=news.run(self.args(t,now='2026-11-17T12:05:00+00:00'))
            self.assertEqual(len(a['data']['items']),1)
            self.assertEqual(a['data']['source_health'][URL]['status'],'not_modified')
            with patch.object(news,'_request',side_effect=SkillError('offline')):
                b=news.run(self.args(t,now='2026-11-17T12:07:00+00:00'))
            self.assertEqual(b['data']['source_health'][URL]['status'],'error')
            self.assertEqual(len(b['data']['items']),1)

    def test_retry_after_is_per_source_and_conditional_request_is_sent(self):
        other='https://other.example.org/rss'
        with tempfile.TemporaryDirectory() as t:
            w=self.setup_workspace(t)
            w.write('config',dict(mode='paper',source_urls=[URL,other],source_min_interval_seconds=60))
            with patch.object(news,'_request',side_effect=[(429,{'retry-after':'600'},b''),SkillError('offline')]):
                a=news.run(self.args(t))['data']['source_health']
            self.assertEqual(a[URL]['next_poll_at'],'2026-11-17T12:13:00Z')
            self.assertEqual(a[other]['next_poll_at'],'2026-11-17T12:04:00Z')
        with tempfile.TemporaryDirectory() as t:
            self.setup_workspace(t)
            with patch.object(news,'_request',return_value=(200,{'etag':'v1','last-modified':'Tue, 17 Nov 2026 12:00:00 GMT'},RSS)):
                news.run(self.args(t))
            def check_headers(url,headers):
                self.assertEqual(headers,{'If-None-Match':'v1','If-Modified-Since':'Tue, 17 Nov 2026 12:00:00 GMT'})
                return 304,{},b''
            with patch.object(news,'_request',side_effect=check_headers):
                news.run(self.args(t,now='2026-11-17T12:05:00+00:00'))

    def test_dtd_private_item_and_unknown_timestamp_rejected(self):
        with self.assertRaises(SkillError):
            news._feed_items(b'<!DOCTYPE rss [<!ENTITY x "boom">]><rss/>',URL)
        for mutation in [dict(url='http://127.0.0.1/secret'),dict(published_at='yesterday')]:
            with tempfile.TemporaryDirectory() as t:
                self.setup_workspace(t); p=Path(t)/'input.json'
                item=dict(id='x',title='title',url='https://example.org/x',source='manual',assets=[])
                item.update(mutation); p.write_text(json.dumps(dict(items=[item])))
                with self.assertRaises(SkillError): news.run(self.args(t,input=str(p)))

    def test_dtd_is_rejected_for_utf16_but_normal_utf16_feed_parses(self):
        xml='<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss [<!ENTITY x "expanded">]><rss><channel><item><guid>x</guid><title>&x;</title><link>https://example.org/x</link></item></channel></rss>'
        for encoding in ('utf-16','utf-16-le','utf-16-be'):
            with self.subTest(encoding=encoding),self.assertRaises(SkillError):
                news._feed_items(xml.encode(encoding),URL)
        clean='<?xml version="1.0" encoding="UTF-16"?>'+RSS.decode()
        self.assertEqual(news._feed_items(clean.encode('utf-16'),URL)[0]['title'],'Bitcoin update')

    def test_request_rejects_redirect_and_body_over_limit(self):
        class Peer:
            def settimeout(self,n): pass
            def connect(self,address): pass
            def close(self): pass
        class Response:
            status=302
            def getheaders(self): return [('Location','http://127.0.0.1/secret')]
            def read(self,n): return b'x'*(n+1)
        class Connection:
            def __init__(self,*a,**kw): pass
            def request(self,*a,**kw): pass
            def getresponse(self): return Response()
            def close(self): pass
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',80))]), \
             patch.object(news.socket,'socket',return_value=Peer()), \
             patch.object(news.http.client,'HTTPConnection',Connection):
            with self.assertRaises(SkillError): news._request('http://example.org/rss',{})
            Response.status=200
            with self.assertRaises(SkillError): news._request('http://example.org/rss',{})

    def test_request_deadline_stops_a_trickling_response(self):
        stopped=Event()
        class Peer:
            def settimeout(self,n): pass
            def connect(self,address): pass
            def shutdown(self,how): stopped.set()
            def close(self): stopped.set()
        class Response:
            status=200
            def getheaders(self): return []
            def read(self,n): stopped.wait(.3); return b'<rss/>'
        class Connection:
            def __init__(self,*a,**kw): pass
            def request(self,*a,**kw): pass
            def getresponse(self): return Response()
            def close(self): pass
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',80))]), \
             patch.object(news.socket,'socket',return_value=Peer()), \
             patch.object(news.http.client,'HTTPConnection',Connection),patch.object(news,'TIMEOUT',.02):
            with self.assertRaises(SkillError): news._request('http://example.org/rss',{})


if __name__ == '__main__': unittest.main()
