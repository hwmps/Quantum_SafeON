// UI 레이어 토글 헤드리스 검증 — 최소 DOM 셰임에서 실제 스크립트를 실행한다.
import fs from 'fs';
const html=fs.readFileSync('src/ui/index.html','utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
const declaredIds=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);

const calls=[];                      // 캔버스 드로잉 호출 기록
const ctx=new Proxy({},{get:(t,p)=>{
  if(p==='canvas')return el('cv');
  if(p==='measureText')return()=>({width:10});
  if(p==='createRadialGradient')return()=>({addColorStop(){}});
  if(typeof p==='string'&&['fillStyle','strokeStyle','lineWidth','font','textAlign','lineJoin'].includes(p))return t[p];
  return (...a)=>{calls.push(p);};
},set:(t,p,v)=>{t[p]=v;return true;}});

const store={};
function el(id){
  if(store[id])return store[id];
  const e={id,value:'',textContent:'',innerHTML:'',checked:true,style:{},className:'',
    files:[],onchange:null,onclick:null,
    getContext:()=>ctx,width:900,height:600,
    getBoundingClientRect:()=>({left:0,top:0,width:900,height:600}),
    appendChild(){},setAttribute(){}};
  store[id]=e;return e;
}
declaredIds.forEach(el);
el('siteW').value='30'; el('scen').value='5'; el('rMode').value='auto';
el('gridR').value='3'; el('gridC').value='4'; el('optK').value='4';
el('clickMode').value='sensor'; el('hzKind').value='fire'; el('hzR').value='6'; el('hzI').value='1';
el('routeFilter').value=''; el('lyDim').checked=true;
globalThis.document={getElementById:id=>store[id]||el(id),
  createElement:t=>({...el('tmp_'+t),tagName:t,click(){}})};
globalThis.location={protocol:'http:'};
globalThis.fetch=()=>Promise.reject(new Error('서버 없음(테스트)'));
globalThis.URL={createObjectURL:()=>'blob:x'};
globalThis.Image=class{set src(v){}};
globalThis.window=globalThis;

const fn=new Function(script+'\n;return {LY,LAYER_SPEC,draw,setLayers,pickRoute,refreshRouteFilter,syncLayerBar,'+
  'get evac(){return evac},set evac(v){evac=v},get zoneInfo(){return zoneInfo},set zoneInfo(v){zoneInfo=v},'+
  'get sensors(){return sensors},set sensors(v){sensors=v},get hazards(){return hazards},set hazards(v){hazards=v},'+
  'get exitsIn(){return exitsIn},set exitsIn(v){exitsIn=v},get originsIn(){return originsIn},set originsIn(v){originsIn=v},'+
  'get selectedIds(){return selectedIds},set selectedIds(v){selectedIds=v},get wx(){return wx},set wx(v){wx=v}};');
const A=fn();
let fail=0; const ok=(c,m)=>{console.log((c?'  ok  ':'  FAIL')+'  '+m);if(!c)fail++;};

console.log('1) 레이어 초기화');
ok(A.LAYER_SPEC.length===13,`레이어 13개 정의 (실제 ${A.LAYER_SPEC.length})`);
ok(A.LY.plan===true&&A.LY.cov===false,'기본값: 도면 on, 커버리지 원 off(가독성 우선)');
ok(store['layerBoxes'].innerHTML.includes('ly_routes')&&store['layerBoxes'].innerHTML.includes('대피 경로'),
   '체크박스 바 렌더 (색 칩 + 이름 = 범례 겸용)');

console.log('2) 프리셋 버튼');
store['lyOnlyEvac'].onclick();
ok(A.LY.routes&&A.LY.exits&&A.LY.workers&&!A.LY.cov&&!A.LY.sensors,'대피만 보기 → 경로·출구·작업자 on, 센서 off');
store['lyOnlySensor'].onclick();
ok(A.LY.cov&&A.LY.sensors&&!A.LY.routes,'센서만 보기 → 커버리지·센서 on, 경로 off');
store['lyAll'].onclick();
ok(Object.values(A.LY).every(v=>v===true),'전체 켜기 → 13개 모두 on');

console.log('3) 개별 토글이 draw() 출력에 반영되는가');
A.sensors=[{xm:5,ym:4,r:null},{xm:12,ym:4,r:null}];
A.hazards=[{id:'F1',kind:'fire',x_m:8,y_m:5,radius_m:6,intensity:1}];
A.exitsIn=[{id:'정문',x_m:29,y_m:10}];
A.originsIn=[{id:'W1',x_m:6,y_m:8,n:24}];
A.wx={있음:true,wd_deg:33.8,ws_ms:3.8,이동_방위_deg:213.8,이동_방위:'남서',설명:[],등급:'보통'};
A.zoneInfo=[{id:'G1',x0:0,y0:0,x1:7.5,y1:6.7,cov:0.1,risk:1.06,downwind:true},
            {id:'G2',x0:7.5,y0:0,x1:15,y1:6.7,cov:0.9,risk:0.5,downwind:false}];
A.selectedIds=['S1'];
A.evac={active:true,exits:[{id:'정문',x_m:29,y_m:10,usable:true}],routes:[
  {origin:'W1',exit:'정문',n:24,지표:{거리_m:12.4,예상_소요_s:10.5},polyline:[{x_m:6,y_m:8},{x_m:29,y_m:10}]},
  {origin:'W2',exit:'정문',n:16,지표:{거리_m:9.9,예상_소요_s:8.3},polyline:[{x_m:20,y_m:12},{x_m:29,y_m:10}]}]};
A.refreshRouteFilter();
ok(store['routeFilter'].innerHTML.includes('W1 → 정문')&&store['routeFilter'].innerHTML.includes('전체 (2개)'),
   '경로 필터 옵션 생성 (전체 + 출발점별)');
const countAfterDraw=()=>{calls.length=0;A.draw();return calls.length};
store['lyAll'].onclick();
const nAll=countAfterDraw();
A.LY.routes=false;A.LY.cov=false;A.LY.hazards=false;A.LY.risk=false;A.LY.weak=false;
A.LY.grid=false;A.LY.downwind=false;A.LY.wind=false;A.LY.exits=false;A.LY.workers=false;A.LY.labels=false;
const nMin=countAfterDraw();
ok(nAll>nMin*1.5,`레이어 끄면 드로잉 호출 감소 (${nAll} → ${nMin})`);
store['lyAll'].onclick();
const nWithLabels=countAfterDraw();
A.LY.labels=false;const nNoLabels=countAfterDraw();
ok(nNoLabels<nWithLabels,`라벨 off → 글자 렌더 감소 (${nWithLabels} → ${nNoLabels})`);
A.LY.labels=true;

console.log('4) 경로 필터·행 클릭');
store['routeFilter'].value='';const nAllRoutes=countAfterDraw();
store['routeFilter'].value='W1';store['lyDim'].checked=false;const nOne=countAfterDraw();
ok(nOne<nAllRoutes,`한 경로만 선택 → 렌더 감소 (${nAllRoutes} → ${nOne})`);
store['lyDim'].checked=true;const nDim=countAfterDraw();
ok(nDim>nOne,`선택 외 흐리게 → 흐린 선도 렌더 (${nOne} → ${nDim})`);
A.LY.routes=false;A.pickRoute('W2');
ok(A.LY.routes===true&&store['routeFilter'].value==='W2','표 행 클릭 → 경로 레이어 자동 on + 해당 경로 선택');
A.pickRoute('W2');
ok(store['routeFilter'].value==='','같은 행 재클릭 → 전체 보기로 복귀');

console.log('5) 예외 상황에서 draw() 가 죽지 않는가');
try{A.evac=null;A.zoneInfo=null;A.sensors=[];A.hazards=[];A.exitsIn=[];A.originsIn=[];A.draw();
  A.refreshRouteFilter();ok(true,'결과·입력이 모두 비어도 draw() 정상');}
catch(e){ok(false,'빈 상태 draw() 예외: '+e.message);}
try{A.wx=null;A.LY.wind=true;A.hazards=[{id:'F1',kind:'smoke',x_m:1,y_m:1,radius_m:3,intensity:0.5}];A.draw();
  ok(true,'기상 없음 + 재해 있음 → 화살표 생략하고 정상');}
catch(e){ok(false,'기상 없음 draw() 예외: '+e.message);}

console.log(fail?`\n실패 ${fail}건`:'\n전체 통과');
process.exit(fail?1:0);
