(() => {
  'use strict';
  const TAU = Math.PI * 2;
  const RAD = Math.PI / 180;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const hero = document.querySelector('#hero-installation');
  const scene = document.querySelector('#scene-preview');
  if (!hero || !scene) return;
  const screen = hero.querySelector('.floating-screen');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  // These layers live outside the clipped illustration so their depth is visible.
  screen.append(hero.querySelector('.hero-album'), hero.querySelector('.hero-lyrics'));
  // One light sculpture continues through every chapter; it never intercepts the page.
  const journeyCanvas = document.createElement('canvas');
  journeyCanvas.id = 'journey-light-canvas';
  journeyCanvas.className = 'journey-light-canvas';
  journeyCanvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(journeyCanvas);

  const identity = () => new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
  const multiply = (a, b) => {
    const out = new Float32Array(16);
    for (let column = 0; column < 4; column++) for (let row = 0; row < 4; row++) {
      let value = 0;
      for (let k = 0; k < 4; k++) value += a[k * 4 + row] * b[column * 4 + k];
      out[column * 4 + row] = value;
    }
    return out;
  };
  const translation = (x, y, z) => { const m = identity(); m[12] = x; m[13] = y; m[14] = z; return m; };
  const scaling = value => { const m = identity(); m[0] = m[5] = m[10] = value; return m; };
  const rotate = (angle, axis) => {
    const c = Math.cos(angle), s = Math.sin(angle), m = identity();
    if (axis === 'x') { m[5] = c; m[6] = s; m[9] = -s; m[10] = c; }
    if (axis === 'y') { m[0] = c; m[2] = -s; m[8] = s; m[10] = c; }
    if (axis === 'z') { m[0] = c; m[1] = s; m[4] = -s; m[5] = c; }
    return m;
  };
  const model = (x, y, z, rx, ry, rz, scale = 1) => multiply(translation(x,y,z), multiply(rotate(rz,'z'), multiply(rotate(ry,'y'), multiply(rotate(rx,'x'), scaling(scale)))));
  const projection = aspect => {
    const f = 1 / Math.tan(20 * RAD), near = .1, far = 50, nf = 1 / (near - far);
    return new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0]);
  };

  const vertexSource = `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    attribute vec2 aUv;
    uniform mat4 uModel;
    uniform mat4 uCamera;
    uniform float uExpand;
    varying vec3 vPosition;
    varying vec3 vNormal;
    varying vec2 vUv;
    void main() {
      vec4 world = uModel * vec4(aPosition + aNormal * uExpand, 1.0);
      vPosition = world.xyz;
      vNormal = normalize(mat3(uModel) * aNormal);
      vUv = aUv;
      gl_Position = uCamera * world;
    }
  `;
  const fragmentSource = `
    precision mediump float;
    uniform vec3 uColourA;
    uniform vec3 uColourB;
    uniform vec2 uPointer;
    uniform float uTime;
    uniform float uCameraZ;
    uniform float uGlow;
    uniform float uMaterial;
    varying vec3 vPosition;
    varying vec3 vNormal;
    varying vec2 vUv;
    void main() {
      vec3 n = normalize(vNormal);
      if (!gl_FrontFacing) n = -n;
      vec3 view = normalize(vec3(0.0,0.0,uCameraZ) - vPosition);
      vec3 light = normalize(vec3(-3.5 + uPointer.x*4.0, 4.5 - uPointer.y*3.0, 5.5) - vPosition);
      float flow = .5 + .5*sin(vUv.x*6.2831853 + uTime*.38 + uMaterial*1.4);
      vec3 palette = mix(uColourA,uColourB,smoothstep(.12,.88,flow));
      float diffuse = max(dot(n,light),0.0);
      float spec = pow(max(dot(reflect(-light,n),view),0.0),70.0);
      float fresnel = pow(1.0-max(dot(n,view),0.0),2.5);
      float softbox = pow(max(0.0,1.0-abs(dot(n,normalize(vec3(.8,.35,.25))))),18.0);
      float strip = pow(max(0.0,1.0-abs(n.y*.8+n.z*.6)),28.0);
      vec3 yellow = vec3(1.0,.831,.165);
      if (uMaterial > 1.5) palette = mix(yellow,uColourB,flow*.18);
      float fill = max(dot(n,normalize(vec3(4.0,-2.0,3.0)-vPosition)),0.0);
      // Coloured lacquer and coloured studio lights keep the ribbons in Halo's palette.
      vec3 colour = palette*(.55+diffuse*.53);
      colour += mix(palette,uColourB,.25)*(fill*.12+fresnel*.23);
      colour += mix(palette,vec3(1.0),.38)*spec*.38;
      colour += mix(palette,yellow,.18)*(softbox*.16+strip*.10);
      if (uGlow > .5) {
        float alpha = .022+.046*fresnel;
        gl_FragColor = vec4(palette*alpha, alpha);
      } else {
        gl_FragColor = vec4(pow(clamp(colour,0.0,1.0),vec3(.93)),1.0);
      }
    }
  `;

  function makeRibbon(gl, a, b, width, thickness, twist, segments = 224) {
    const radial = 14, vertices = [], indices = [];
    for (let i = 0; i <= segments; i++) {
      const u = i / segments * TAU;
      const nx0 = Math.cos(u)/a, ny0 = Math.sin(u)/b;
      const length = Math.hypot(nx0,ny0), nx = nx0/length, ny = ny0/length;
      const angle = u*twist, ct = Math.cos(angle), st = Math.sin(angle);
      for (let j = 0; j <= radial; j++) {
        const v = j/radial*TAU, cv = Math.cos(v), sv = Math.sin(v);
        const outward = cv*width*ct-sv*thickness*st;
        const z = cv*width*st+sv*thickness*ct;
        const normalR = cv*ct-sv*st, normalZ = cv*st+sv*ct;
        vertices.push(Math.cos(u)*a+nx*outward,Math.sin(u)*b+ny*outward,Math.sin(u*3)*.06+z,nx*normalR,ny*normalR,normalZ,i/segments,j/radial);
        if (i < segments && j < radial) {
          const first=i*(radial+1)+j, next=first+radial+1;
          indices.push(first,next,first+1,next,next+1,first+1);
        }
      }
    }
    const buffer=gl.createBuffer(), index=gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,index); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,new Uint16Array(indices),gl.STATIC_DRAW);
    return {buffer,index,count:indices.length,a,b,padding:width+thickness+.25};
  }

  function createSculpture(canvas, kind) {
    let gl;
    try { gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:true,powerPreference:'low-power'}); } catch { canvas.dataset.engine='fallback';return null; }
    if (!gl) { canvas.dataset.engine='fallback'; return null; }
    const shader = (type, source) => {
      const value=gl.createShader(type);gl.shaderSource(value,source);gl.compileShader(value);
      if (!gl.getShaderParameter(value,gl.COMPILE_STATUS)) { gl.deleteShader(value);return null; }
      return value;
    };
    const vertex=shader(gl.VERTEX_SHADER,vertexSource), fragment=shader(gl.FRAGMENT_SHADER,fragmentSource);
    if (!vertex || !fragment) { canvas.dataset.engine='fallback';return null; }
    const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
    if (!gl.getProgramParameter(program,gl.LINK_STATUS)) { canvas.dataset.engine='fallback';return null; }
    gl.deleteShader(vertex);gl.deleteShader(fragment);gl.useProgram(program);
    const uniforms={};
    ['uModel','uCamera','uExpand','uColourA','uColourB','uPointer','uTime','uCameraZ','uGlow','uMaterial'].forEach(name=>uniforms[name]=gl.getUniformLocation(program,name));
    const attributes=['aPosition','aNormal','aUv'].map(name=>gl.getAttribLocation(program,name));
    const meshes=kind==='hero'
      ? [makeRibbon(gl,3.65,2.3,.13,.045,2),makeRibbon(gl,3.84,2.52,.065,.025,1),makeRibbon(gl,4.08,2.64,.025,.025,0)]
      : kind==='journey'
        ? [makeRibbon(gl,5.45,4.25,.058,.03,2,112),makeRibbon(gl,5.9,4.6,.028,.022,1,112)]
        : [makeRibbon(gl,2.4,1.45,.065,.035,2,176),makeRibbon(gl,2.6,1.55,.025,.022,1,176)];
    let camera=identity(), rect, frames=0, lost=false, cameraDistance=12;
    const readyClass=kind==='hero'?'sculpture-ready':kind==='scene'?'scene-sculpture-ready':'journey-sculpture-ready';
    const renderer={canvas,kind,visible:true,dirty:true,lastDraw:0,draw};
    const resize=()=>{
      rect=canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const ratio=kind==='journey'
        ? Math.min(devicePixelRatio||1,innerWidth<741?.85:1,1600/rect.width)
        : Math.min(devicePixelRatio||1,innerWidth<741?1.25:1.65);
      canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);
      gl.viewport(0,0,canvas.width,canvas.height);
      camera=multiply(projection(rect.width/rect.height),translation(0,0,-9.2));
      renderer.dirty=true;
    };
    new ResizeObserver(resize).observe(canvas);resize();
    canvas.addEventListener('webglcontextlost',event=>{
      event.preventDefault();lost=true;canvas.dataset.engine='fallback';
      canvas.parentElement.classList.remove(readyClass);
    });
    canvas.dataset.engine='webgl';canvas.dataset.renderState='ready';
    canvas.parentElement.classList.add(readyClass);
    function draw(time,pose,colours) {
      if (lost || !rect?.width) return;
      gl.useProgram(program);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.disable(gl.CULL_FACE);
      gl.uniform3fv(uniforms.uColourA,colours[0]);gl.uniform3fv(uniforms.uColourB,colours[1]);
      gl.uniform2f(uniforms.uPointer,pose.px,pose.py);gl.uniform1f(uniforms.uTime,time);
      let x=0,y=0,scale=1;
      if (kind==='scene') {
        const art=scene.querySelector('.scene-art').getBoundingClientRect();
        rect=canvas.getBoundingClientRect();
        const span=9.2*2*Math.tan(20*RAD), pixel=rect.height/span;
        x=((art.left+art.width/2-rect.left)/rect.width-.5)*span*rect.width/rect.height;
        y=-((art.top+art.height/2-rect.top)/rect.height-.5)*span;
        scale=(art.width*.94)/(pixel*2.4);
      } else if (kind==='journey') {
        const span=9.2*2*Math.tan(20*RAD);
        const width=span*rect.width/rect.height;
        scale=Math.min(width/11.4,1.65);
        x=Math.sin(pose.chapter*TAU*.85)*width*.075;
        y=(Math.cos(pose.chapter*TAU*.6)*.08-.08)*span;
      }
      const models=meshes.map((mesh,i)=> {
        const direction=i%2===0?1:-1;
        const rx=kind==='journey'
          ? -.2+Math.sin(pose.chapter*TAU+time*.045+i)*.28
          : (i===0?.3:-.55)+Math.sin(time*.32+i*1.4)*.36+pose.y*RAD*.6;
        const ry=kind==='journey'
          ? Math.sin(pose.chapter*TAU*.6+i*.8)*.3
          : (i===0?.22:-.42)+Math.sin(time*.39+i*2)*.72+pose.x*RAD*.8;
        const rz=kind==='journey'
          ? -.22+pose.chapter*TAU*.9+pose.progress*.45+i*.24+direction*time*.022
          : -.22+direction*time*(i===0?.115:.145)+i*.7;
        return model(x,y+Math.sin(time*.55+i)*.05,-.25-i*.08,rx,ry,rz,scale);
      });
      if (kind==='hero') {
        // Fit every tilted ellipse, including its glow, into the actual canvas frustum.
        // The camera pulls back immediately and eases inward, avoiding clipped manual turns.
        const tangent=Math.tan(20*RAD), aspect=rect.width/rect.height;
        let required=8.8;
        meshes.forEach((mesh,index)=>{
          const m=models[index];
          for(let step=0;step<40;step++) {
            const angle=step/40*TAU, vx=Math.cos(angle)*mesh.a, vy=Math.sin(angle)*mesh.b;
            const wx=m[0]*vx+m[4]*vy+m[12], wy=m[1]*vx+m[5]*vy+m[13], wz=m[2]*vx+m[6]*vy+m[14];
            required=Math.max(required,wz+mesh.padding+Math.max((Math.abs(wx)+mesh.padding)/(tangent*aspect),(Math.abs(wy)+mesh.padding)/tangent)*1.07);
          }
        });
        cameraDistance=required>cameraDistance?required:cameraDistance+(required-cameraDistance)*.04;
        camera=multiply(projection(aspect),translation(0,0,-cameraDistance));
        canvas.dataset.cameraDistance=cameraDistance.toFixed(3);
      }
      gl.uniformMatrix4fv(uniforms.uCamera,false,camera);
      gl.uniform1f(uniforms.uCameraZ,kind==='hero'?cameraDistance:9.2);
      const drawMesh=(mesh,i,expand,glow)=>{
        gl.bindBuffer(gl.ARRAY_BUFFER,mesh.buffer);gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,mesh.index);
        attributes.forEach((attribute,j)=>{
          gl.enableVertexAttribArray(attribute);gl.vertexAttribPointer(attribute,j===2?2:3,gl.FLOAT,false,32,j===0?0:j===1?12:24);
        });
        gl.uniformMatrix4fv(uniforms.uModel,false,models[i]);gl.uniform1f(uniforms.uExpand,expand);
        gl.uniform1f(uniforms.uGlow,glow);gl.uniform1f(uniforms.uMaterial,i);
        gl.drawElements(gl.TRIANGLES,mesh.count,gl.UNSIGNED_SHORT,0);
      };
      gl.disable(gl.BLEND);gl.depthMask(true);meshes.forEach((mesh,i)=>drawMesh(mesh,i,0,0));
      gl.enable(gl.BLEND);gl.blendFuncSeparate(gl.ONE,gl.ONE,gl.ONE,gl.ONE_MINUS_SRC_ALPHA);gl.depthMask(false);
      meshes.forEach((mesh,i)=>{drawMesh(mesh,i,.09,1);drawMesh(mesh,i,.19,1);});
      gl.depthMask(true);frames++;
      if (frames===1 || frames%12===0) {canvas.dataset.frames=String(frames);canvas.dataset.renderTime=time.toFixed(3);}
      renderer.dirty=false;
    }
    return renderer;
  }

  const heroRenderer=createSculpture(document.querySelector('#hero-light-canvas'),'hero');
  const sceneRenderer=createSculpture(document.querySelector('#scene-light-canvas'),'scene');
  const journeyRenderer=createSculpture(journeyCanvas,'journey');
  const renderers=[heroRenderer,sceneRenderer,journeyRenderer].filter(Boolean);
  const pose={x:0,y:0,px:0,py:0};
  const journeyPose={x:0,y:0,px:0,py:0,progress:0,chapter:0};
  let heroVisible=true,compact=false;
  let pointerX=0,pointerY=0,dragX=0,dragY=0,dragging=false,dragDistance=0,lastPointerX=0,lastPointerY=0;
  let paused=false,time=1.8,last=0,lastDraw=0,lastPalette=0,manualPose=false;
  let colours=[new Float32Array([.141,.314,.91]),new Float32Array([.957,.482,.608])];
  const refreshMotion=()=>{
    const wasPaused=paused;
    paused=reduced.matches||document.body.classList.contains('motion-reduced')||document.body.classList.contains('motion-paused');
    renderers.forEach(renderer=>renderer.dirty=true);
    if(journeyRenderer)journeyRenderer.visible=!reduced.matches;
    if(reduced.matches)hero.style.setProperty('--scroll-depth','0');
    else if(wasPaused&&!paused)onScroll();
    if (paused) document.querySelectorAll('.effect-stage,.lyric-stage').forEach(panel=>{panel.style.setProperty('--panel-x','0');panel.style.setProperty('--panel-y','0');});
  };
  new MutationObserver(refreshMotion).observe(document.body,{attributes:true,attributeFilter:['class']});
  reduced.addEventListener('change',refreshMotion);refreshMotion();

  if('IntersectionObserver' in window) {
    const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
      if(entry.target===hero)heroVisible=entry.isIntersecting;
      const renderer=entry.target===hero?heroRenderer:sceneRenderer;
      if (renderer) {renderer.visible=entry.isIntersecting;renderer.dirty=true;}
    }),{rootMargin:'80px'});
    observer.observe(hero);observer.observe(scene);
  }
  function fitInstallation() {
    compact=innerWidth<=740;
    if(compact) {
      const scale=clamp((hero.clientWidth-20)/720,.32,.72);
      hero.style.setProperty('--installation-scale',scale.toFixed(4));
      hero.style.setProperty('--installation-height',`${Math.ceil(510*scale+88)}px`);
      hero.style.setProperty('--installation-hit-pad',`${Math.max(0,(48/scale-document.querySelector('#hero-play').offsetWidth)/2).toFixed(2)}px`);
      dragX=clamp(dragX,-16,16);dragY=clamp(dragY,-9,9);
    } else {
      ['--installation-scale','--installation-height','--installation-hit-pad'].forEach(property=>hero.style.removeProperty(property));
    }
    manualPose=true;
    renderers.forEach(renderer=>renderer.dirty=true);
  }
  new ResizeObserver(fitInstallation).observe(hero);
  addEventListener('resize',fitInstallation,{passive:true});fitInstallation();
  const recenter=()=>{dragX=dragY=pointerX=pointerY=0;manualPose=true;renderers.forEach(renderer=>renderer.dirty=true);hero.dataset.rotation='centered';};
  document.querySelector('#recenter-installation').addEventListener('click',recenter);
  hero.addEventListener('pointerdown',event=>{
    if (event.target.closest('button,a,input') || reduced.matches || event.button!==0) return;
    dragging=true;dragDistance=0;lastPointerX=event.clientX;lastPointerY=event.clientY;
    hero.classList.add('is-dragging');hero.setPointerCapture(event.pointerId);
  });
  hero.addEventListener('pointermove',event=>{
    if (reduced.matches || (paused&&!dragging)) return;
    const rect=hero.getBoundingClientRect();
    if (dragging) {
      const dx=event.clientX-lastPointerX,dy=event.clientY-lastPointerY;
      dragX=clamp(dragX+dx*.14,compact?-16:-32,compact?16:32);dragY=clamp(dragY-dy*.1,compact?-9:-18,compact?9:18);dragDistance+=Math.abs(dx);
      lastPointerX=event.clientX;lastPointerY=event.clientY;hero.dataset.rotation='custom';
      manualPose=true;
    } else if (event.pointerType==='mouse') {
      pointerX=clamp((event.clientX-rect.left)/rect.width*2-1,-1,1);
      pointerY=clamp((event.clientY-rect.top)/rect.height*2-1,-1,1);
    }
    renderers.forEach(renderer=>renderer.dirty=true);
  });
  const release=()=>{dragging=false;hero.classList.remove('is-dragging');};
  hero.addEventListener('pointerup',release);hero.addEventListener('pointercancel',release);hero.addEventListener('lostpointercapture',release);
  hero.addEventListener('pointerleave',()=>{if(!dragging){pointerX=pointerY=0;renderers.forEach(renderer=>renderer.dirty=true);}});
  hero.addEventListener('keydown',event=>{
    if (event.target!==hero) return;
    if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(event.key)) {
      event.preventDefault();
      if (event.key==='Home') recenter();
      if (event.key==='ArrowLeft') dragX=clamp(dragX-7,compact?-16:-32,compact?16:32);
      if (event.key==='ArrowRight') dragX=clamp(dragX+7,compact?-16:-32,compact?16:32);
      if (event.key==='ArrowUp') dragY=clamp(dragY-5,compact?-9:-18,compact?9:18);
      if (event.key==='ArrowDown') dragY=clamp(dragY+5,compact?-9:-18,compact?9:18);
      if(event.key!=='Home')hero.dataset.rotation='custom';
      manualPose=true;
      renderers.forEach(renderer=>renderer.dirty=true);
    }
  });
  function onScroll() {
    if(paused)return;
    const rect=hero.getBoundingClientRect();
    const depth=reduced.matches?0:clamp((-rect.top+110)/650,0,1);
    hero.style.setProperty('--scroll-depth',depth.toFixed(3));
    if(heroRenderer)heroRenderer.dirty=true;
  }
  addEventListener('scroll',onScroll,{passive:true});onScroll();

  document.querySelectorAll('.effect-stage,.lyric-stage').forEach(panel=>{
    panel.addEventListener('pointermove',event=>{
      if(paused||event.pointerType!=='mouse')return;
      const rect=panel.getBoundingClientRect();
      panel.style.setProperty('--panel-x',clamp((event.clientX-rect.left)/rect.width*2-1,-1,1).toFixed(3));
      panel.style.setProperty('--panel-y',clamp((event.clientY-rect.top)/rect.height*2-1,-1,1).toFixed(3));
    });
    panel.addEventListener('pointerleave',()=>{panel.style.setProperty('--panel-x','0');panel.style.setProperty('--panel-y','0');});
  });
  scene.addEventListener('pointermove',event=>{
    if(paused||event.pointerType!=='mouse')return;
    const rect=scene.getBoundingClientRect();
    scene.style.setProperty('--scene-x',clamp((event.clientX-rect.left)/rect.width*2-1,-1,1).toFixed(3));
    scene.style.setProperty('--scene-y',clamp((event.clientY-rect.top)/rect.height*2-1,-1,1).toFixed(3));
  });
  scene.addEventListener('pointerleave',()=>{scene.style.setProperty('--scene-x','0');scene.style.setProperty('--scene-y','0');});
  new MutationObserver(()=>{
    if(sceneRenderer)sceneRenderer.dirty=true;
    const target=scene.querySelector(scene.dataset.scene==='cinema'?'.cinema-song':'.scene-content');
    if(!paused)target.animate([{opacity:.25,transform:'translateZ(-100px) rotateX(7deg) scale(.94)'},{opacity:1,transform:'translateZ(0) rotateX(0) scale(1)'}],{duration:950,easing:'cubic-bezier(.2,.8,.2,1)'});
  }).observe(scene,{attributes:true,attributeFilter:['data-scene']});
  if ('IntersectionObserver' in window) {
    document.body.classList.add('depth-ready');
    const sectionObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{
      if(entry.isIntersecting){entry.target.classList.add('is-in-view');sectionObserver.unobserve(entry.target);}
    }),{threshold:.12});
    document.querySelectorAll('.section').forEach(section=>sectionObserver.observe(section));
  }
  const readColour=text=>{
    const values=text.match(/[\d.]+/g);
    if(text.startsWith('#')){const hex=text.slice(1);return new Float32Array([0,2,4].map(index=>parseInt(hex.slice(index,index+2),16)/255));}
    return values?.length>=3?new Float32Array(values.slice(0,3).map(value=>Number(value)/(text.startsWith('color(')?1:255))):null;
  };
  function frame(now) {
    requestAnimationFrame(frame);
    const delta=last?Math.min((now-last)/1000,.05):0;last=now;
    if(document.hidden)return;
    if(!paused)time+=delta;
    if(now-lastDraw<(innerWidth<741?30:15))return;lastDraw=now;
    // The HTML interface remains interactive even when a device cannot create WebGL.
    const anyVisible=heroVisible||renderers.some(renderer=>renderer.visible);
    if(!anyVisible)return;
    const rootStyle=getComputedStyle(document.documentElement);
    const sharedTime=parseFloat(rootStyle.getPropertyValue('--journey-time'));
    if(!paused&&Number.isFinite(sharedTime)&&sharedTime>0)time=sharedTime+1.8;
    if(now-lastPalette>1500){
      const first=readColour(rootStyle.getPropertyValue('--colour-one').trim()),second=readColour(rootStyle.getPropertyValue('--colour-two').trim());
      if(first&&second)colours=[first,second];lastPalette=now;
    }
    const targetX=dragX+pointerX*(compact?5:12)+(reduced.matches?0:Math.sin(time*.48)*(compact?3:6));
    const targetY=dragY-pointerY*(compact?3:8)+(reduced.matches?0:Math.sin(time*.37)*(compact?2:4));
    if(!paused||manualPose) {
      pose.x+=(targetX-pose.x)*(paused?1:.065);pose.y+=(targetY-pose.y)*(paused?1:.065);pose.px=pointerX;pose.py=pointerY;
      if(heroVisible){
        hero.style.setProperty('--turn-x',pose.x.toFixed(3));hero.style.setProperty('--turn-y',pose.y.toFixed(3));
        hero.style.setProperty('--float',reduced.matches?'0':Math.sin(time*.73).toFixed(3));
        hero.style.setProperty('--layer-lift',reduced.matches?'0':(1+Math.sin(time*.44)).toFixed(3));
      }
    }
    manualPose=false;
    if(!paused&&journeyRenderer) {
      const progress=clamp(parseFloat(rootStyle.getPropertyValue('--journey-progress'))||0,0,1);
      const chapter=clamp(parseFloat(rootStyle.getPropertyValue('--journey-chapter'))||0,0,1);
      journeyPose.progress+=(progress-journeyPose.progress)*.12;
      journeyPose.chapter+=(chapter-journeyPose.chapter)*.12;
      journeyCanvas.dataset.chapter=journeyPose.chapter.toFixed(4);
    }
    renderers.forEach(renderer=>{
      if(!renderer.visible||paused&&!renderer.dirty)return;
      if(renderer.kind==='scene'&&scene.dataset.scene!=='orbit')return;
      if(renderer.kind==='journey'&&!renderer.dirty&&now-renderer.lastDraw<(compact?80:45))return;
      renderer.draw(time,renderer.kind==='journey'?journeyPose:pose,colours);
      renderer.lastDraw=now;
    });
  }
  requestAnimationFrame(frame);
})();
