const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/js/main.js'),'utf8');
function actualFunction(name,next) {
  return source.slice(source.indexOf('  function '+name+'('),source.indexOf('  function '+next+'('));
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness() {
  const requests=[],features=[],stats={catalogs:0,selections:0,clears:0};
  const context={Promise,AbortController,URL,WeakMap,Number,Math,Array,Object,
    cfg:{datasetFeatureLimit:1000,datasetMinLoadZoom:12,datasetRadiusMeters:400},
    state:{activeDataset:{id:'flurstuecke',source:{type:'wfs'}},datasets:{requestSerial:0,lastViewportKey:'',loading:false},
      datasetSource:{addFeatures:f=>features.push(...f),clear:()=>{features.length=0;stats.clears++;}},
      datasetLayer:{visible:true,getVisible(){return this.visible;},setVisible(v){this.visible=v;}}},
    viewport:{key:'active::project-berlin',zoom:16,bbox:[13.3,52.5,13.5,52.6],center:[13.4,52.55]},
    ensureObject:v=>v||{},asText:(v,f='')=>String(v??f),numOr:(v,f)=>Number.isFinite(Number(v))?Number(v):f,
    asBool:(v,f)=>v??f,clamp:(v,a,b)=>Math.min(b,Math.max(a,v)),normalizeSourceType:v=>v,
    updateViewportIndicators(){},logError(){},logWarn(){},setToast(){},clearTimeout,
    DEFAULT_DATASET_BATCH_SIZE:100,DATASET_BATCH_DELAY_MS:0,
    window:{AbortController,setTimeout:f=>setImmediate(f),location:{href:'http://localhost/'}},
    loadDatasetFeatures:(dataset,viewport,options)=>new Promise(resolve=>requests.push({options,resolve,viewport})),
    postParcelCatalog:()=>stats.catalogs++,autoSelectCoordinateParcel:()=>stats.selections++,
    applyDataset:(dataset,result)=>{features.length=0;features.push(...result.features);},
    buildDatasetSourceUrl:id=>'/api/datasets/'+id+'/source'
  };
  context.getCurrentViewportContext=()=>context.viewport;
  vm.createContext(context);
  vm.runInContext(actualFunction('setDatasetZoomVisibility','scheduleActiveDatasetReload')+
    actualFunction('reloadActiveDatasetForViewport','refreshActiveDatasetStyle')+
    actualFunction('buildDatasetFetchUrl','loadDatasetFeatures'),context);
  return {context,requests,features,stats};
}
test('moving/zooming during a progressive load does not abort or restart the same location',async()=>{
  const {context:c,requests,features,stats}=harness();
  const load=c.reloadActiveDatasetForViewport();assert.equal(requests.length,1);
  for(let i=0;i<10;i++) {c.viewport.zoom=15+i/10;await c.reloadActiveDatasetForViewport();}
  assert.equal(requests.length,1);assert.equal(requests[0].options.signal.aborted,false);
  for(let page=0;page<10;page++) {
    requests[page].resolve({features:Array.from({length:100},(_,i)=>({id:page*100+i})),hasMore:page<9,nextOffset:(page+1)*100});
    await tick();await tick();
  }
  await load;
  assert.equal(features.length,1000);assert.equal(stats.catalogs,1);assert.equal(stats.selections,1);
  await c.reloadActiveDatasetForViewport();assert.equal(requests.length,10);
  c.viewport.zoom=10;c.setDatasetZoomVisibility();assert.equal(features.length,1000);assert.equal(stats.clears,0);
  c.viewport.zoom=17;c.setDatasetZoomVisibility();await c.reloadActiveDatasetForViewport();assert.equal(requests.length,10);
});
test('batch append enforces 1,000 total even for an oversized response',async()=>{
  const {context:c,requests,features}=harness();const load=c.reloadActiveDatasetForViewport();
  requests[0].resolve({features:Array(600).fill({}),hasMore:true,nextOffset:600});await tick();await tick();
  requests[1].resolve({features:Array(600).fill({}),hasMore:true,nextOffset:1200});await load;
  assert.equal(features.length,1000);assert.equal(requests.length,2);
});
test('project changes replace the request; pan/zoom never changes its URL or cache key',async()=>{
  const {context:c,requests}=harness();
  const a=c.buildDatasetFetchUrl(c.state.activeDataset,c.viewport,{});
  c.viewport.zoom=19;
  assert.equal(c.buildDatasetFetchUrl(c.state.activeDataset,c.viewport,{}),a);
  const first=c.reloadActiveDatasetForViewport();
  c.viewport={...c.viewport,key:'active::new-property',center:[13.41,52.55]};
  const second=c.reloadActiveDatasetForViewport();
  assert.equal(requests[0].options.signal.aborted,true);assert.equal(requests.length,2);
  requests[0].resolve({features:[]});requests[1].resolve({features:[]});await Promise.all([first,second]);
});
test('feature styles and labels are reused; edits and style changes invalidate them',()=>{
  let revision=1,labels=0;
  const feature={getRevision:()=>revision},base={},bundle={defaultSet:{polygon:base},ruleSets:{}};
  const c={window:{ol:{style:{}}},ol:{style:{Style:class {constructor(options){this.options=options;}}}},
    featureStyleCache:new WeakMap(),hasUsableStyleContract:()=>true,
    getOrCreateDatasetStyleBundle:()=>bundle,selectStyleRule:()=>null,
    styleForGeometry:set=>set.polygon,labelOptionsForRule:()=>({priority:5}),
    featureLabelStyle:()=>{labels++;return {};},numOr:(v,f)=>v??f,clamp:(v,a,b)=>Math.min(b,Math.max(a,v))};
  vm.createContext(c);
  vm.runInContext(actualFunction('getFeatureStyleForDataset','buildMapboxTileUrl'),c);
  const first=c.getFeatureStyleForDataset({},feature,'Polygon',1);
  for(let i=0;i<100;i++) assert.equal(c.getFeatureStyleForDataset({},feature,'Polygon',i+1),first);
  assert.equal(labels,1);assert.equal(first[0],base);assert.equal(first[1].options.zIndex,105);
  revision++;assert.notEqual(c.getFeatureStyleForDataset({},feature,'Polygon',1),first);assert.equal(labels,2);
  c.getOrCreateDatasetStyleBundle=()=>({...bundle});
  c.getFeatureStyleForDataset({},feature,'Polygon',1);assert.equal(labels,3);
});
test('early empty hydration does not prevent selecting a parcel from the final batch',()=>{
  const {context:c}=harness();let features=[],serialized=0,selected=0;
  c.state.parcelSelection={hydrated:true,byId:{},revision:0,defaultCoordinateSelectionDone:false};
  c.state.location={anchorProjected:[0,0]};c.state.datasetSource.getFeatures=()=>features;
  c.datasetLooksLikeParcels=()=>true;c.parcelSelectionItems=()=>[];
  c.parcelFromFeature=feature=>{serialized++;return {parcelId:feature.id};};
  c.postParcelSelection=()=>selected++;
  vm.runInContext(actualFunction('autoSelectCoordinateParcel','primitiveFeatureProperties'),c);
  assert.equal(c.autoSelectCoordinateParcel(),false);
  assert.equal(c.state.parcelSelection.defaultCoordinateSelectionDone,false);
  features=[{id:'parcel',getGeometry:()=>({getArea:()=>100,intersectsCoordinate:()=>true})}];
  assert.equal(c.autoSelectCoordinateParcel(),true);
  assert.equal(serialized,1);assert.equal(selected,1);
  assert.equal(c.state.parcelSelection.byId.parcel.parcelId,'parcel');
});
