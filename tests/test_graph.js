const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(__dirname+'/../web/app.js','utf8');
const beforeMap=code.split('const map=L.map')[0];
const sandbox={console};
vm.runInNewContext(beforeMap+`\nthis.TrackGraph=TrackGraph;this.hav=hav;`,sandbox);
const TrackGraph=sandbox.TrackGraph;
const graph=new TrackGraph([
 {id:'1',ids:['a','b'],coordinates:[[29.7,-95.4],[29.701,-95.4]]},
 {id:'2',ids:['b','c'],coordinates:[[29.701,-95.4],[29.702,-95.4]]},
 {id:'3',ids:['d','e'],coordinates:[[29.8,-95.4],[29.801,-95.4]]},
]);
const a=graph.point(0,0.5),b=graph.point(1,0.5),c=graph.point(2,0.5);
assert(Math.abs(graph.path(a,b).meters-111.195)<0.5,'half edge + half edge = 111m');
assert(Math.abs(graph.path(a,a).meters)<1e-8,'same point = 0');
assert(Math.abs(graph.path(a,graph.point(0,0.7)).meters-22.239)<0.5,'same edge');
assert(graph.path(a,c)===null,'disconnected tracks');
assert(graph.snap([29.7005,-95.39999]).distanceToTrack<3,'snapping');
const pts=graph.sampleMainPath(5,[]);assert(pts.length===5,'five auto markers');
assert(graph.path(pts[0],pts[4])!==null,'sampled path connected');
console.log('OK: graph, snapping, path along rail, disconnection, auto placement');
