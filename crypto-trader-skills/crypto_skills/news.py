"""Bounded public RSS/Atom polling and durable, versioned offline news imports."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import xml.etree.ElementTree as ET
from threading import Event, Timer
from datetime import timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from .core import SkillError, Workspace, decimal, utc, iso, digest, require

MAX_BODY=1024*1024
MAX_ITEMS=10000
TIMEOUT=8


def validate_url(url, resolve=False):
    """Resolve once and return vetted addresses so the transport can pin its peer."""
    require(isinstance(url,str) and 1 <= len(url) <= 4096 and not any(c.isspace() for c in url),
            'Invalid public URL')
    try:
        parts=urlsplit(url)
        require(parts.scheme in ('http','https') and parts.hostname and not parts.username
                and not parts.password and not parts.fragment, 'Only credential-free HTTP(S) URLs are allowed')
        port=parts.port or (443 if parts.scheme == 'https' else 80)
        require(port in (80,443), 'Only standard public HTTP(S) ports are supported')
        host=parts.hostname
        require('%' not in host and host.lower() not in ('localhost','localhost.localdomain')
                and not host.lower().endswith(('.localhost','.local','.internal')), 'Private hostname rejected')
        try:
            literal=ipaddress.ip_address(host)
        except ValueError:
            literal=None
        if literal is not None:
            require(literal.is_global and not (getattr(literal,'ipv4_mapped',None)
                    and not literal.ipv4_mapped.is_global), 'Private or reserved address rejected')
        addresses=[]
        if resolve:
            for family, _, _, _, address in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM):
                ip=ipaddress.ip_address(address[0])
                require(ip.is_global and not (getattr(ip,'ipv4_mapped',None)
                        and not ip.ipv4_mapped.is_global), 'Private or reserved DNS address rejected')
                if (family,address) not in addresses: addresses.append((family,address))
            require(addresses, 'Public source did not resolve')
        return parts,port,addresses
    except (OSError,ValueError) as exc:
        raise SkillError(f'Invalid public URL: {exc}') from exc


def _request(url, headers):
    parts,port,addresses=validate_url(url,resolve=True)
    conn=http.client.HTTPConnection(parts.hostname,port,timeout=TIMEOUT)
    peer=None
    timer=None
    expired=Event()
    def expire():
        expired.set()
        if peer is not None:
            try: peer.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            peer.close()
    try:
        # Connect directly to the checked address; avoid a second DNS lookup/rebinding.
        family,address=addresses[0]
        peer=socket.socket(family,socket.SOCK_STREAM)
        peer.settimeout(TIMEOUT)
        timer=Timer(TIMEOUT,expire)
        timer.daemon=True
        timer.start()
        peer.connect(address)
        if parts.scheme == 'https':
            peer=ssl.create_default_context().wrap_socket(peer,server_hostname=parts.hostname)
        conn.sock=peer
        path=parts.path or '/'
        if parts.query: path+='?'+parts.query
        conn.request('GET',path,headers=dict({'User-Agent':'crypto-skills/1 (public RSS reader)',
                                             'Accept':'application/rss+xml, application/atom+xml, application/xml',
                                             'Accept-Encoding':'identity'},**headers))
        response=conn.getresponse()
        result_headers={k.lower():v for k,v in response.getheaders()}
        require(not 300 <= response.status < 400 or response.status == 304,'Feed redirects are rejected')
        require(result_headers.get('content-encoding','identity').lower() == 'identity',
                'Compressed feed responses are not accepted')
        length=result_headers.get('content-length')
        require(length is None or int(length) <= MAX_BODY,'Feed exceeds 1MiB')
        body=response.read(MAX_BODY+1)
        require(not expired.is_set(),'Feed exceeded request deadline')
        require(len(body)<=MAX_BODY,'Feed exceeds 1MiB')
        return response.status,result_headers,body
    except (OSError,ValueError,http.client.HTTPException) as exc:
        raise SkillError(f'Public feed request failed: {exc}') from exc
    finally:
        if timer is not None: timer.cancel()
        conn.close()
        if peer is not None: peer.close()


def _text(node, names):
    for child in node:
        if child.tag.rsplit('}',1)[-1] in names:
            return ''.join(child.itertext()).strip()
    return ''


class _FeedTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise SkillError('DTD/entity declarations are not accepted')


def _feed_items(body, source):
    require(len(body)<=MAX_BODY,'Feed exceeds 1MiB')
    require(b'<!DOCTYPE' not in body.upper() and b'<!ENTITY' not in body.upper(),
            'DTD/entity declarations are not accepted')
    try:
        root=ET.fromstring(body,parser=ET.XMLParser(target=_FeedTreeBuilder()))
    except ET.ParseError as exc:
        raise SkillError(f'Invalid feed XML: {exc}') from exc
    require(root.tag.rsplit('}',1)[-1] in ('rss','feed','RDF'), 'Expected RSS or Atom feed')
    nodes=[n for n in root.iter() if n.tag.rsplit('}',1)[-1] in ('item','entry')]
    require(len(nodes)<=1000,'Feed has more than 1000 items')
    result=[]
    for node in nodes:
        title=_text(node,('title',))
        link=_text(node,('link',))
        for child in node:
            if child.tag.rsplit('}',1)[-1] == 'link' and child.get('href') and child.get('rel','alternate') == 'alternate':
                link=child.get('href'); break
        link=urljoin(source,link)
        identity=_text(node,('guid','id')) or link
        published=_text(node,('pubDate','published','updated','date'))
        item=dict(id=identity,title=title,url=link,source=source,assets=[])
        if published:
            try:
                item['published_at']=iso(utc(published))
            except SkillError:
                try:
                    item['published_at']=iso(parsedate_to_datetime(published))
                except (ValueError,TypeError) as exc:
                    raise SkillError('Invalid feed publication timestamp') from exc
        result.append(item)
    return result


def _normalize(item):
    require(isinstance(item,dict),'News item must be an object')
    result={}
    for key,bound in (('id',4096),('title',2000),('source',4096)):
        value=item.get(key)
        require(isinstance(value,str) and 0<len(value.strip())<=bound,f'Invalid news {key}')
        result[key]=value.strip()
    validate_url(item.get('url'))
    result['url']=item['url']
    assets=item.get('assets')
    require(isinstance(assets,list) and len(assets)<=100 and all(isinstance(a,str)
            and re.fullmatch('[A-Z0-9]{1,20}',a) for a in assets),'Invalid explicit news assets')
    result['assets']=sorted(set(assets))
    if item.get('published_at') is not None:
        result['published_at']=iso(item['published_at'])
    return result


def _merge(existing, incoming, current):
    rows={digest([i['source'],i['id']]):i for i in existing}
    for item in incoming:
        clean=_normalize(item)
        key=digest([clean['source'],clean['id']])
        version=digest(clean)
        old=rows.get(key,{})
        versions=list(old.get('versions',[]))
        if version in versions and version != old.get('version'):
            rows[key]=dict(old,last_seen=iso(current))
            continue
        if version not in versions:
            require(len(versions)<100,'News item exceeds 100 versions; archive before polling')
            versions.append(version)
        rows[key]=dict(clean,version=version,versions=versions,
                       first_seen=old.get('first_seen',iso(current)),
                       last_seen=iso(current))
    require(len(rows)<=MAX_ITEMS,'News store exceeds 10000 items; archive before polling')
    return list(rows.values())


def _next_poll(current, interval, headers):
    delay=interval
    match=re.search(r'(?:^|,)\s*max-age=(\d+)',headers.get('cache-control',''),re.I)
    if match: delay=max(delay,min(int(match[1]),86400*7))
    retry=headers.get('retry-after')
    if retry:
        try:
            value=int(retry)
        except ValueError:
            try: value=max(0,(parsedate_to_datetime(retry)-current).total_seconds())
            except (ValueError,TypeError): value=interval
        delay=max(delay,min(value,86400*7))
    return iso(current+timedelta(seconds=delay))


def run(args):
    w=Workspace(args.workspace)
    current=utc(getattr(args,'now',None))
    with w.lock():
        config=w.config
        require(bool(getattr(args,'input',None)) != bool(getattr(args,'fetch',False)),
                'Specify exactly one of --input or --fetch')
        if (w.state/'news.json').exists():
            previous=w.read('news')['data']
        else:
            previous={}
        items=previous.get('items',[])
        health=dict(previous.get('source_health',{}))
        if getattr(args,'input',None):
            try:
                path=Path(args.input)
                require(path.stat().st_size<=MAX_BODY,'News import exceeds 1MiB')
                raw=json.loads(path.read_text(encoding='utf-8'))
                require(isinstance(raw,dict) and isinstance(raw.get('items'),list)
                        and len(raw['items'])<=1000,'Expected at most 1000 news items')
                items=_merge(items,raw['items'],current)
                health['import']=dict(status='ok',last_checked=iso(current),last_success=iso(current),
                                      path=str(path.resolve()))
            except (OSError,ValueError,TypeError,KeyError) as exc:
                health['import']=dict(status='error',last_checked=iso(current),error=str(exc))
                w.write('news',dict(items=items,source_health=health,checked_at=iso(current)),now=current)
                raise SkillError(f'News import failed: {exc}') from exc
        else:
            urls=config.get('source_urls',[])
            require(isinstance(urls,list) and 1<=len(urls)<=20 and all(isinstance(u,str) for u in urls)
                    and len(set(urls))==len(urls),
                    'Configure 1..20 distinct public feed source_urls')
            interval=decimal(config.get('source_min_interval_seconds',60))
            require(60<=interval<=86400*7,'Feed poll interval must be 60 seconds..7 days')
            for url in urls:
                old=dict(health.get(url,{}))
                next_poll=iso(current+timedelta(seconds=float(interval)))
                try:
                    validate_url(url)
                    if old.get('next_poll_at') and current<utc(old['next_poll_at']):
                        health[url]=dict(old,status='rate_limited',last_checked=iso(current))
                        continue
                    headers={}
                    if old.get('etag'): headers['If-None-Match']=old['etag']
                    if old.get('last_modified'): headers['If-Modified-Since']=old['last_modified']
                    status,response_headers,body=_request(url,headers)
                    next_poll=_next_poll(current,float(interval),response_headers)
                    state=dict(old,last_checked=iso(current),next_poll_at=next_poll,http_status=status)
                    for header,key in (('etag','etag'),('last-modified','last_modified')):
                        if response_headers.get(header): state[key]=response_headers[header]
                    if status==304:
                        require(old.get('last_success'), '304 received before any successful feed')
                        state.update(status='not_modified',last_success=iso(current))
                    else:
                        require(status==200,f'Feed returned HTTP {status}')
                        items=_merge(items,_feed_items(body,url),current)
                        state.update(status='ok',last_success=iso(current))
                    state.pop('error',None)
                    health[url]=state
                except (SkillError,OSError,ValueError,TypeError,KeyError) as exc:
                    health[url]=dict(old,status='error',last_checked=iso(current),error=str(exc),
                                     next_poll_at=next_poll)
        return w.write('news',dict(items=items,source_health=health,checked_at=iso(current)),
                       inputs={'config':w.read('config')['digest']},now=current)
