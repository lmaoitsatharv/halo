(() => {
  'use strict';
  const figure = document.querySelector('.music-polaroid');
  if (!figure) return;
  const image = figure.querySelector('img');
  const stage = document.createElement('div');
  stage.className = 'music-model-stage';
  image.before(stage);stage.append(image);
  stage.insertAdjacentHTML('beforeend','<div class="music-model-shadow" aria-hidden="true"></div><canvas class="music-model-canvas" id="music-model-canvas" aria-hidden="true"></canvas><div class="model-hint" aria-hidden="true"><span>DRAG TO EXPLORE ↔</span><span>ORIGINAL 3D ART</span></div>');
  const canvas = stage.querySelector('canvas');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const identity = () => new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
  function mul(a,b) {
    const m = new Float32Array(16);
    for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)m[c*4+r]+=a[k*4+r]*b[c*4+k];
    return m;
  }
  const translate = (x,y,z) => {const m=identity();m[12]=x;m[13]=y;m[14]=z;return m;};
  function rotate(angle,axis) {
    const m=identity(),s=Math.sin(angle),c=Math.cos(angle);
    if(axis==='x'){m[5]=c;m[6]=s;m[9]=-s;m[10]=c;}
    else{m[0]=c;m[2]=-s;m[8]=s;m[10]=c;}
    return m;
  }
  function nodeMatrix(n) {
    if(n.matrix)return new Float32Array(n.matrix);
    const [x,y,z,w]=n.rotation||[0,0,0,1],s=n.scale||[1,1,1],t=n.translation||[0,0,0];
    return new Float32Array([(1-2*y*y-2*z*z)*s[0],(2*x*y+2*w*z)*s[0],(2*x*z-2*w*y)*s[0],0,(2*x*y-2*w*z)*s[1],(1-2*x*x-2*z*z)*s[1],(2*y*z+2*w*x)*s[1],0,(2*x*z+2*w*y)*s[2],(2*y*z-2*w*x)*s[2],(1-2*x*x-2*y*y)*s[2],0,...t,1]);
  }
  const norm = v => {const d=Math.hypot(...v);return v.map(x=>x/d);};
  const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const eye=[0,.28,1.05],z=norm(eye),x=norm(cross([0,1,0],z)),y=cross(z,x);
  const view=new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-x.reduce((a,v,i)=>a+v*eye[i],0),-y.reduce((a,v,i)=>a+v*eye[i],0),-z.reduce((a,v,i)=>a+v*eye[i],0),1]);
  const vertex='attribute vec3 aPosition;attribute vec3 aNormal;uniform mat4 uModel;uniform mat4 uCamera;varying vec3 vNormal;varying vec3 vPosition;void main(){vec4 p=uModel*vec4(aPosition,1.);vPosition=p.xyz;vNormal=normalize(mat3(uModel)*aNormal);gl_Position=uCamera*p;}';
  const fragment='precision mediump float;uniform vec3 uColour;uniform float uRoughness;varying vec3 vNormal;varying vec3 vPosition;void main(){vec3 n=normalize(vNormal);if(!gl_FrontFacing)n=-n;vec3 v=normalize(vec3(0.,.28,1.05)-vPosition);vec3 l=normalize(vec3(-.7,1.2,.9)-vPosition);float d=max(dot(n,l),0.);float s=pow(max(dot(n,normalize(l+v)),0.),mix(95.,12.,uRoughness));float rim=pow(1.-max(dot(n,v),0.),3.);vec3 c=uColour*(.48+d*.7)+vec3(1.,.97,.87)*s*(1.-uRoughness)*.8+uColour*rim*.15;c=c/(vec3(.92)+c)*1.3;gl_FragColor=vec4(pow(max(c,vec3(0.)),vec3(1./2.2)),1.);}';
  let gl,program,position,normal;
  const locations={};
  let camera=identity(),meshes=[],allocated=[],visible=false,dirty=true,paused=reduced.matches;
  let time=0,last=0,lastDraw=0,frames=0,loadStarted=false,contextLost=false,requestVersion=0,controller;
  let drag=0,tilt=0,pointer=0,dragging=false,pointerId=null,lastX=0,lastY=0,rotation=-.5;
  function release() {
    dragging=false;stage.classList.remove('is-dragging');
    if(pointerId!==null&&stage.hasPointerCapture(pointerId))stage.releasePointerCapture(pointerId);
    pointerId=null;
  }
  function fallback() {
    requestVersion++;controller?.abort();release();
    allocated.forEach(buffer=>gl?.deleteBuffer(buffer));allocated=[];meshes=[];
    if(program)gl.deleteProgram(program);program=null;
    stage.classList.remove('is-ready');
    stage.removeAttribute('tabindex');stage.removeAttribute('aria-label');stage.removeAttribute('role');
    canvas.dataset.engine='fallback';canvas.dataset.renderState='fallback';
  }
  function initialize() {
    try {
      gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:true,powerPreference:'low-power'});
      if(!gl||gl.isContextLost())return false;
      function compile(type,source) {
        const shader=gl.createShader(type);
        gl.shaderSource(shader,source);gl.compileShader(shader);
        if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){gl.deleteShader(shader);throw Error('Shader unavailable');}
        return shader;
      }
      program=gl.createProgram();
      const v=compile(gl.VERTEX_SHADER,vertex),f=compile(gl.FRAGMENT_SHADER,fragment);
      gl.attachShader(program,v);gl.attachShader(program,f);gl.linkProgram(program);
      gl.deleteShader(v);gl.deleteShader(f);
      if(!gl.getProgramParameter(program,gl.LINK_STATUS))return false;
      ['uModel','uCamera','uColour','uRoughness'].forEach(name=>locations[name]=gl.getUniformLocation(program,name));
      position=gl.getAttribLocation(program,'aPosition');normal=gl.getAttribLocation(program,'aNormal');
      resize();return true;
    }catch{return false;}
  }
  function resize() {
    if(!gl||contextLost)return;
    const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;
    const ratio=Math.min(devicePixelRatio||1,innerWidth<741?1.2:1.6);
    canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);
    gl.viewport(0,0,canvas.width,canvas.height);
    const f=1/Math.tan(.25),a=rect.width/rect.height,n=.01,far=20;
    const projection=new Float32Array([f/a,0,0,0,0,f,0,0,0,0,(far+n)/(n-far),-1,0,0,2*far*n/(n-far),0]);
    camera=mul(projection,view);dirty=true;
  }
  if('ResizeObserver' in window)new ResizeObserver(resize).observe(canvas);
  else addEventListener('resize',resize,{passive:true});
  function refresh() {paused=reduced.matches||document.body.classList.contains('motion-paused');dirty=true;}
  reduced.addEventListener('change',refresh);
  new MutationObserver(refresh).observe(document.body,{attributes:true,attributeFilter:['class']});refresh();
  stage.addEventListener('pointerdown',event=>{
    if(!stage.classList.contains('is-ready')||event.button!==0)return;
    dragging=true;lastX=event.clientX;lastY=event.clientY;pointerId=event.pointerId;
    stage.classList.add('is-dragging');stage.setPointerCapture(pointerId);
  });
  stage.addEventListener('pointermove',event=>{
    if(!stage.classList.contains('is-ready'))return;
    if(dragging){
      drag+=(event.clientX-lastX)*.009;tilt=Math.max(-.45,Math.min(.45,tilt+(event.clientY-lastY)*.006));
      lastX=event.clientX;lastY=event.clientY;dirty=true;stage.dataset.rotation='custom';
    }else if(event.pointerType==='mouse'){
      const rect=stage.getBoundingClientRect();pointer=(event.clientX-rect.left)/rect.width*2-1;
    }
  });
  ['pointerup','pointercancel','lostpointercapture'].forEach(name=>stage.addEventListener(name,release));
  stage.addEventListener('pointerleave',()=>{if(!dragging){pointer=0;dirty=true;}});
  stage.addEventListener('keydown',event=>{
    if(!stage.classList.contains('is-ready')||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(event.key))return;
    event.preventDefault();
    if(event.key==='Home'){drag=tilt=pointer=0;stage.dataset.rotation='centered';}
    else{
      if(event.key==='ArrowLeft')drag-=.25;if(event.key==='ArrowRight')drag+=.25;
      if(event.key==='ArrowUp')tilt=Math.max(-.45,tilt-.12);if(event.key==='ArrowDown')tilt=Math.min(.45,tilt+.12);
      stage.dataset.rotation='custom';
    }
    dirty=true;
  });
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();contextLost=true;fallback();});
  function readAccessor(j,binary,id) {
    const a=j.accessors[id],v=j.bufferViews[a.bufferView];
    const components={SCALAR:1,VEC2:2,VEC3:3,VEC4:4}[a.type],size={5126:4,5125:4,5123:2,5121:1}[a.componentType];
    const Type={5126:Float32Array,5125:Uint32Array,5123:Uint16Array,5121:Uint8Array}[a.componentType];
    if(!components||!Type)throw Error('Unsupported model data');
    const data=new Type(a.count*components),view=new DataView(binary);
    const offset=(v.byteOffset||0)+(a.byteOffset||0),stride=v.byteStride||size*components;
    const getter={5126:'getFloat32',5125:'getUint32',5123:'getUint16',5121:'getUint8'}[a.componentType];
    for(let i=0;i<a.count;i++)for(let c=0;c<components;c++)data[i*components+c]=view[getter](offset+i*stride+c*size,true);
    return data;
  }
  async function load() {
    if(loadStarted||contextLost)return;
    loadStarted=true;
    if(!initialize()){fallback();return;}
    const version=++requestVersion;
    controller=new AbortController();
    try {
      const response=await fetch('assets/music-sculpture.glb',{signal:controller.signal});
      if(!response.ok)throw Error('Model unavailable');
      const buffer=await response.arrayBuffer();
      if(version!==requestVersion||contextLost||gl.isContextLost())return;
      const header=new DataView(buffer);
      if(buffer.byteLength<28||header.getUint32(0,true)!==0x46546c67||header.getUint32(4,true)!==2)throw Error('Invalid model');
      const jsonLength=header.getUint32(12,true);
      if(header.getUint32(16,true)!==0x4e4f534a||20+jsonLength+8>buffer.byteLength)throw Error('Invalid model');
      const j=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,20,jsonLength)));
      const binary=buffer.slice(20+jsonLength+8),nextMeshes=[];
      function upload(target,data) {
        const value=gl.createBuffer();if(!value)throw Error('Buffer unavailable');
        allocated.push(value);gl.bindBuffer(target,value);gl.bufferData(target,data,gl.STATIC_DRAW);return value;
      }
      function visit(index,parent) {
        const n=j.nodes[index],matrix=mul(parent,nodeMatrix(n));
        if(n.mesh!==undefined&&n.name?.startsWith('HERO_'))j.meshes[n.mesh].primitives.forEach(p=>{
          const vertices=readAccessor(j,binary,p.attributes.POSITION),normals=readAccessor(j,binary,p.attributes.NORMAL),indices=readAccessor(j,binary,p.indices);
          const vertexBuffer=upload(gl.ARRAY_BUFFER,vertices),normalBuffer=upload(gl.ARRAY_BUFFER,normals),indexBuffer=upload(gl.ELEMENT_ARRAY_BUFFER,indices);
          const material=j.materials[p.material].pbrMetallicRoughness;
          if(indices instanceof Uint32Array&&!gl.getExtension('OES_element_index_uint'))throw Error('Unsupported model indices');
          const type=indices instanceof Uint32Array?gl.UNSIGNED_INT:indices instanceof Uint8Array?gl.UNSIGNED_BYTE:gl.UNSIGNED_SHORT;
          nextMeshes.push({vertexBuffer,normalBuffer,indexBuffer,matrix,colour:material.baseColorFactor.slice(0,3),roughness:material.roughnessFactor,count:indices.length,type});
        });
        (n.children||[]).forEach(child=>visit(child,matrix));
      }
      j.scenes[j.scene||0].nodes.forEach(index=>visit(index,identity()));
      if(version!==requestVersion||contextLost||gl.isContextLost())return;
      if(!nextMeshes.length)throw Error('Empty model');
      meshes=nextMeshes;resize();dirty=true;
    }catch{
      if(version===requestVersion)fallback();
    }
  }
  if('IntersectionObserver' in window) {
    const preload=new IntersectionObserver(entries=>{
      if(!entries[0].isIntersecting)return;
      preload.unobserve(stage);load();
    },{rootMargin:'350px 0px'});
    preload.observe(stage);
    new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;dirty=true;},{rootMargin:'100px 0px'}).observe(stage);
  }else{visible=true;load();}
  function frame(now) {
    requestAnimationFrame(frame);
    const dt=last?Math.min((now-last)/1000,.05):0;last=now;
    if(document.hidden||!visible||!meshes.length||contextLost)return;
    if(gl.isContextLost()){contextLost=true;fallback();return;}
    if(!paused)time+=dt;
    if(paused&&!dirty)return;
    if(now-lastDraw<(innerWidth<741?32:16))return;lastDraw=now;
    const desired=-.5+drag+(paused?0:Math.sin(time*.44)*.23+pointer*.3);
    rotation+=(desired-rotation)*(paused||dragging?1:.07);
    const root=mul(rotate(rotation,'y'),mul(rotate(tilt+(paused?0:Math.sin(time*.5)*.04),'x'),translate(0,-.195,0)));
    gl.useProgram(program);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);gl.uniformMatrix4fv(locations.uCamera,false,camera);
    meshes.forEach(mesh=>{
      gl.bindBuffer(gl.ARRAY_BUFFER,mesh.vertexBuffer);gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,3,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ARRAY_BUFFER,mesh.normalBuffer);gl.enableVertexAttribArray(normal);gl.vertexAttribPointer(normal,3,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,mesh.indexBuffer);gl.uniformMatrix4fv(locations.uModel,false,mul(root,mesh.matrix));
      gl.uniform3fv(locations.uColour,mesh.colour);gl.uniform1f(locations.uRoughness,mesh.roughness);gl.drawElements(gl.TRIANGLES,mesh.count,mesh.type,0);
    });
    if(!frames) {
      if(gl.isContextLost()||gl.getError()!==gl.NO_ERROR){fallback();return;}
      canvas.dataset.engine='webgl';canvas.dataset.source='Higgsfield';canvas.dataset.meshes=String(meshes.length);canvas.dataset.renderState='ready';
      stage.tabIndex=0;stage.setAttribute('role','group');
      stage.setAttribute('aria-label','Original 3D music sculpture. Drag or use arrow keys to turn the headphones and record. Press Home to reset.');
      stage.classList.add('is-ready');
    }
    frames++;
    if(frames===1||frames%12===0){canvas.dataset.frames=String(frames);canvas.dataset.renderTime=time.toFixed(3);}
    dirty=false;
  }
  requestAnimationFrame(frame);
})();
