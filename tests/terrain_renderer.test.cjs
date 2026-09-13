const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/js/terrain-renderer.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('adjacent exports share one map render with correct crop, reusable buffers and style invalidation',async()=>{
  const messages=[],centres=[],crops=[],handlers={},renders=[];let design='light',map;
  const view={setCenter(p){centres.push(p);},setZoom(z){this.zoom=z;}};
  const ol={proj:{fromLonLat:p=>p},View:class {constructor(){return view;}},Map:class {
    constructor(){map=this;this.handlers={};} setSize(){}setLayers(){}getView(){return view;}
    getViewport(){return {querySelectorAll:()=>[]};}on(n,f){this.handlers[n]=f;}un(n,f){if(this.handlers[n]===f)delete this.handlers[n];}
    renderSync(){renders.push(view.zoom);this.handlers.rendercomplete?.();}dispose(){}
  }};
  const parent={postMessage:p=>messages.push(p)};
  const document={referrer:'http://localhost:5104/cad',createElement:()=>({getContext:()=>({fillRect(){},
    getImageData(x,y){crops.push([x,y]);const data=new Uint8ClampedArray(256*256*4);data[0]=x/128;return {data};}})})};
  const window={parent,ol,addEventListener:(name,fn)=>handlers[name]=fn,TERRAIN_BASEMAP_CONFIG:{},
    VectoplanBasemap:{storageKey:'design',readPreference:()=>design,create:(config,id,announce)=>{
      announce();return {designId:id,provider:'openfreemap',styleLoading:false,dispose(){}};
    }}};
  await vm.runInNewContext(source,{window,document,ol,URL,Map,Math,Number,Uint8ClampedArray,setTimeout,clearTimeout,
    setInterval,clearInterval,queueMicrotask});await tick();
  const request=async(id,z,x,y)=>{handlers.message({source:parent,origin:'http://localhost:5104',data:{contract:'vectoplan-terrain-map.v1',type:'tile',revision:messages.filter(m=>m.type==='state').at(-1).revision,id,z,x,y}});await tick();};
  await request(1,18,140832,85970);await request(2,18,140833,85970);await request(3,18,140832,85971);await request(4,18,140833,85971);
  assert.equal(renders.length,1);
  assert.deepEqual(crops,[[128,128],[128,384],[384,128],[384,384]]);
  assert.equal(messages.filter(m=>m.type==='tile').length,4);
  const first=messages.find(m=>m.id===1);new Uint8Array(first.pixels)[0]=255;
  await request(5,18,140832,85970);assert.equal(new Uint8Array(messages.find(m=>m.id===5).pixels)[0],1);
  assert.equal(centres[0][0],(140833/2**18)*360-180);
  design='dark';handlers.storage({key:'design'});await tick();await request(6,18,140832,85970);
  assert.equal(renders.length,2);assert.equal(messages.find(m=>m.id===6).designId,'dark');
  handlers.pagehide();
});
