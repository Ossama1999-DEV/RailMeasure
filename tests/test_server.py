import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

OSM = b'''<osm version="0.6">
<node id="1" lat="29.700" lon="-95.400"/>
<node id="2" lat="29.701" lon="-95.400"/>
<node id="3" lat="29.702" lon="-95.400"/>
<node id="4" lat="29.700" lon="-95.401"><tag k="name" v="Station test"/><tag k="railway" v="station"/></node>
<way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="railway" v="light_rail"/></way>
<relation id="123"><member type="way" ref="10" role=""/><member type="node" ref="4" role="stop"/><tag k="type" v="route"/><tag k="route" v="tram"/><tag k="name" v="Test Line"/></relation>
</osm>'''
class ServerTest(unittest.TestCase):
    def test_parse_and_cache(self):
        with tempfile.TemporaryDirectory() as d,patch.object(app,'CACHE',Path(d)),patch.object(app.railway,'fetch_route_tree',return_value=OSM) as fetch:
            data=app.route_payload(123)
            self.assertEqual(data['name'],'Test Line')
            self.assertEqual(len(data['ways']),1)
            self.assertEqual(data['ways'][0]['ids'],['1','2','3'])
            self.assertEqual(data['stations'][0]['name'],'Station test')
            self.assertEqual(data['ways'][0]['coordinates'][0],[29.7,-95.4])
            app.route_payload(123)
            self.assertEqual(fetch.call_count,1)
if __name__=='__main__':unittest.main()
