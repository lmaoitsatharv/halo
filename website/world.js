(() => {
  'use strict';
  const body = document.body;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const fine = matchMedia('(hover: hover) and (pointer: fine)');
  const forcedColours = matchMedia('(forced-colors: active)');
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ease = 'cubic-bezier(.18,.8,.22,1)';
  const runningAnimations = new Set();
  const hoverAnimations = new Map();
  let paused = reduced.matches || body.classList.contains('motion-paused');
  let px = 0, py = 0, pointerX = -100, pointerY = -100, cursorX = -100, cursorY = -100, pointerScene = false;
  let pointerTarget = null;
  let scroll = scrollY, time = 0, last = 0, lastDraw = 0, introDone = false;
  const cursor = document.querySelector('#world-cursor');
  const meter = document.querySelector('.scroll-meter');
  const canvas = document.querySelector('#world-canvas');
  const ctx = canvas.getContext('2d');
  let width = innerWidth, height = innerHeight, ratio = 1;

  document.querySelectorAll('h1,h2').forEach(heading => {
    const lines = heading.innerHTML.split(/<br\s*\/?\s*>/i);
    heading.replaceChildren(...lines.map(html => {
      const line = document.createElement('span');
      line.className = 'heading-line'; line.innerHTML = html; return line;
    }));
    heading.classList.add('chapter-heading');
  });

  const ribbon = document.createElement('div');
  ribbon.className = 'kinetic-ribbon'; ribbon.setAttribute('aria-hidden', 'true');
  ribbon.innerHTML = '<div class="ribbon-track">' + Array(5).fill('<span>GOOD MUSIC</span><b>✳</b><span>GREAT LIGHT</span><b>✳</b><span>ALL THE FEELS</span><b>✳</b>').join('') + '</div>';
  document.querySelector('.intro-band').after(ribbon);
  const track = ribbon.firstElementChild;
  const particles = Array.from({length: 34}, (_, i) => ({
    x: (i % 2 ? -1 : 1) * (.84 + (i * .173 % .7)),
    y: (i * .618 % 2) - 1,
    z: .25 + (i * .371 % 1.8),
    angle: i * 1.8, size: i % 3 ? 3 : 8,
    colour: ['#2450e8', '#f47b9b', '#ffd42a'][i % 3]
  }));

  const chapters = [...document.querySelectorAll('main > section')].map((element, index) => ({
    element, index, top: 0, height: 0, centre: 0, direction: index % 2 ? 1 : -1
  }));
  const chapterByElement = new Map(chapters.map(chapter => [chapter.element, chapter]));
  const selectors = '.section-heading,.light-experience,.fine-tuning,.lyrics-copy,.lyric-experience,.scenes-heading,.scene-notes>p,.mood-copy,.integration-copy,.connection-art,.details-intro,.faq,.roadmap>div,.roadmap>ul';
  const blocks = [...document.querySelectorAll(selectors)].map(element => {
    element.classList.add('spatial-block');
    const chapter = chapterByElement.get(element.closest('section'));
    return {element, chapter, direction: chapter?.direction || 1, active: false, entered: false};
  });
  const byElement = new Map(blocks.map(block => [block.element, block]));
  function animate(element, frames, options) {
    if (paused) return;
    const animation = element.animate(frames, options);
    runningAnimations.add(animation);
    animation.finished.catch(() => {}).finally(() => {
      if (options.fill !== 'forwards' || animation.playState === 'idle') runningAnimations.delete(animation);
    });
    return animation;
  }
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    const block = byElement.get(entry.target);
    block.active = entry.isIntersecting;
    if (entry.isIntersecting && !block.entered) {
      block.entered = true;
      if (!paused) {
        const children = [...block.element.children].filter(el => el.tagName !== 'CANVAS');
        children.forEach((child, i) => animate(child, [
          {opacity: 0, transform: `perspective(1400px) translate3d(${block.direction * 28}px,65px,-140px) rotateX(13deg) rotateY(${block.direction * 8}deg)`},
          {opacity: 1, transform: 'perspective(1400px) translate3d(0,0,0) rotateX(0) rotateY(0)'}
        ], {duration: 1100, delay: i * 70, easing: ease, fill: 'backwards'}));
      }
    }
  }), {rootMargin:'80px 0px', threshold:.08});
  blocks.forEach(block => observer.observe(block.element));

  function measure() {
    width = innerWidth; height = innerHeight;
    ratio = Math.min(devicePixelRatio || 1, width < 741 ? 1 : 1.5);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    chapters.forEach(chapter => {
      const rect = chapter.element.getBoundingClientRect();
      chapter.top = rect.top + scrollY; chapter.height = rect.height;
      chapter.centre = chapter.top + chapter.height / 2;
    });
    updateScroll();
  }
  function updateScroll() {
    scroll = scrollY;
    const progress = clamp(scroll / Math.max(1, document.documentElement.scrollHeight - height), 0, 1);
    const point = scroll + height / 2;
    let chapterPosition = 0;
    if (chapters.length > 1) {
      chapterPosition = chapters.length - 1;
      if (point <= chapters[0].centre) chapterPosition = 0;
      else for (let i = 0; i < chapters.length - 1; i++) {
        if (point > chapters[i + 1].centre) continue;
        const span = Math.max(1, chapters[i + 1].centre - chapters[i].centre);
        chapterPosition = i + clamp((point - chapters[i].centre) / span, 0, 1);
        break;
      }
    }
    meter.style.setProperty('--page-progress', progress.toFixed(4));
    document.documentElement.style.setProperty('--journey-progress', progress.toFixed(4));
    document.documentElement.style.setProperty('--journey-chapter', (chapterPosition / Math.max(1, chapters.length - 1)).toFixed(4));
  }
  addEventListener('resize', measure, {passive:true});
  addEventListener('scroll', updateScroll, {passive:true});
  measure();
  let measureFrame;
  const scheduleMeasure = () => {
    if (measureFrame) return;
    measureFrame = requestAnimationFrame(() => {measureFrame = 0;measure();});
  };
  if ('ResizeObserver' in window) {
    const layoutObserver = new ResizeObserver(scheduleMeasure);
    chapters.forEach(chapter => layoutObserver.observe(chapter.element));
  }
  document.fonts.ready.then(scheduleMeasure);

  const cursorAllowed = () => !paused && fine.matches && !forcedColours.matches;
  function updateCursorFeedback() {
    const dragging = pointerTarget?.closest('.hero-installation,.music-model-stage.is-ready');
    const link = pointerTarget?.closest('a,button,summary,input');
    const isDrag = !!dragging && !link;
    cursor.classList.toggle('is-link', !!link);
    cursor.classList.toggle('is-drag', isDrag);
    const label = isDrag ? 'DRAG' : '↗';
    if (cursor.firstElementChild.textContent !== label) cursor.firstElementChild.textContent = label;
  }

  function placeCursor() {
    cursor.style.transform = `translate3d(${cursorX}px,${cursorY}px,0) translate(-50%,-50%)`;
  }
  function resetCursor() {
    cursor.classList.remove('is-pressed');
    if (body.classList.contains('cursor-live')) body.classList.remove('cursor-live');
  }
  function updatePointer(event, snap = false) {
    if (event.pointerType !== 'mouse' || !fine.matches) return false;
    pointerX = event.clientX; pointerY = event.clientY;
    px = pointerX / width * 2 - 1; py = pointerY / height * 2 - 1;
    pointerTarget = event.target;
    if (!cursorAllowed()) return false;
    if (snap || !body.classList.contains('cursor-live')) {
      cursorX = pointerX; cursorY = pointerY;
      placeCursor();
    }
    body.classList.add('cursor-live');
    pointerScene = !!event.target.closest('#scene-preview');
    updateCursorFeedback();
    return true;
  }
  document.addEventListener('pointermove', event => {
    if (!updatePointer(event)) return;
    cursor.classList.toggle('is-pressed', !!(event.buttons & 1));
  }, {passive:true});
  document.addEventListener('pointerdown', event => {
    if (!updatePointer(event, true)) return;
    cursor.classList.toggle('is-pressed', event.button === 0);
  }, {passive:true});
  document.addEventListener('pointerup', () => cursor.classList.remove('is-pressed'), {passive:true});
  document.addEventListener('pointercancel', resetCursor, {passive:true});
  document.addEventListener('contextmenu', resetCursor);
  document.documentElement.addEventListener('pointerleave', resetCursor);
  document.addEventListener('keydown', resetCursor);
  addEventListener('blur', resetCursor);
  document.addEventListener('visibilitychange', () => {if (document.hidden) resetCursor();});

  document.querySelectorAll('.button,.nav-repo,.hero-actions .text-link').forEach(button => {
    button.classList.add('magnetic');
    button.addEventListener('pointermove', event => {
      if (paused || event.pointerType !== 'mouse') return;
      const rect = button.getBoundingClientRect();
      button.style.setProperty('--magnet-x', String((event.clientX - rect.left - rect.width / 2) * .12));
      button.style.setProperty('--magnet-y', String((event.clientY - rect.top - rect.height / 2) * .2));
    });
    button.addEventListener('pointerleave', () => {
      button.style.setProperty('--magnet-x', '0');button.style.setProperty('--magnet-y', '0');
    });
  });
  document.querySelectorAll('.effect-choice,.lyric-picker button,.scene-picker button').forEach((button, i) => {
    button.addEventListener('pointerenter', event => {
      if (!fine.matches || event.pointerType !== 'mouse' || paused) return;
      const previous = hoverAnimations.get(button);
      if (previous) {previous.cancel();runningAnimations.delete(previous);}
      hoverAnimations.set(button, animate(button, [
        {transform:'perspective(600px) rotateX(0) rotateY(0)'},
        {transform:`perspective(600px) rotateX(-7deg) rotateY(${i % 2 ? 5 : -5}deg) scale(1.035)`}
      ], {duration:350, easing:ease, fill:'forwards'}));
    });
    button.addEventListener('pointerleave', () => {
      const previous = hoverAnimations.get(button);
      if (previous) {previous.cancel();runningAnimations.delete(previous);hoverAnimations.delete(button);}
      animate(button, [{transform:'perspective(600px) rotateX(-6deg) scale(1.035)'}, {transform:'none'}], {duration:450, easing:ease});
    });
  });

  function refresh() {
    const nextPaused = reduced.matches || body.classList.contains('motion-paused');
    // Cursor cleanup changes the body's class too. Only react to a motion
    // transition, so the observer cannot keep triggering its own callback.
    if (nextPaused === paused) return;
    paused = nextPaused;
    if (paused) {
      runningAnimations.forEach(animation => animation.cancel());
      runningAnimations.clear();hoverAnimations.clear();
      resetCursor();
      blocks.forEach(({element}) => ['--drift-x','--drift-y','--depth-z','--depth-x','--depth-y'].forEach(name => element.style.setProperty(name,'0')));
      cursor.style.transform = 'translate3d(-100px,-100px,0)';
      body.dataset.worldMotion='paused';
    }
  }
  reduced.addEventListener('change', refresh);
  const refreshCursor = () => {if (!cursorAllowed()) resetCursor();};
  fine.addEventListener('change', refreshCursor);
  forcedColours.addEventListener('change', refreshCursor);
  new MutationObserver(refresh).observe(body, {attributes:true,attributeFilter:['class']});

  async function entrance() {
    if (paused || location.hash && location.hash !== '#') {introDone = true;return;}
    const intro = document.createElement('div');
    intro.className = 'world-intro'; intro.setAttribute('aria-hidden','true');
    intro.innerHTML = '<i class="intro-ring"></i><i class="intro-ring"></i><div class="intro-brand">HALO<span>.</span></div><p>A LITTLE ATMOSPHERE FOR YOUR MUSIC</p>';
    body.append(intro);
    const assetsReady = document.fonts.ready;
    const brandBeat = new Promise(resolve => setTimeout(resolve, 650));
    await Promise.all([assetsReady, brandBeat]);
    intro.classList.add('is-leaving');
    const delay = 260;
    const headlines = [...document.querySelectorAll('h1 .heading-line')];
    headlines.forEach((line, i) => animate(line, [
      {opacity:0, transform:'perspective(1200px) rotateX(-65deg) rotateY(-12deg) translate3d(-30px,70px,-180px)'},
      {opacity:1, transform:'perspective(1200px) rotateX(0) rotateY(0) translate3d(0,0,0)'}
    ], {duration:1200, delay:delay+i*130, easing:ease, fill:'backwards'}));
    animate(document.querySelector('.hero-installation'), [
      {opacity:0,transform:'perspective(1600px) translate3d(120px,70px,-450px) rotateY(-30deg) rotateX(12deg) scale(.72)'},
      {opacity:1,transform:'perspective(1600px) translate3d(0,0,0) rotateY(0) rotateX(0) scale(1)'}
    ],{duration:1800,delay:300,easing:ease,fill:'backwards'});
    ['.site-header','.hero-copy .eyebrow','.hero-description','.hero-actions','.hero-footnote'].forEach((selector,i) => animate(document.querySelector(selector),[
      {opacity:0,transform:'perspective(1000px) translate3d(0,28px,-80px) rotateX(10deg)'},
      {opacity:1,transform:'none'}
    ],{duration:900,delay:delay+i*100,easing:ease,fill:'backwards'}));
    setTimeout(() => {intro.remove();introDone=true;body.dataset.entrance='complete';measure();},900);
  }
  entrance();

  function drawWorld() {
    ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
    const yaw = Math.sin(time*.12)*.1 + px*.06;
    const cy = scroll*.00022;
    particles.forEach((p,i) => {
      const sourceY = ((p.y + cy + time*.012) % 2.6) - 1.3;
      const x3 = p.x*Math.cos(yaw) + p.z*Math.sin(yaw);
      const z3 = p.z*Math.cos(yaw) - p.x*Math.sin(yaw);
      const depth = 1.8/(1.8+z3);
      const x = width/2 + x3*width*.62*depth;
      const y = height/2 + sourceY*height*.6*depth + py*10;
      if (x > width*.14 && x < width*.86) return;
      ctx.save();ctx.translate(x,y);ctx.rotate(p.angle + time*.15);ctx.globalAlpha=.32*depth;
      ctx.strokeStyle=p.colour;ctx.lineWidth=1.4*depth;
      const size=p.size*depth;
      ctx.beginPath();ctx.moveTo(-size,0);ctx.lineTo(size,0);ctx.moveTo(0,-size);ctx.lineTo(0,size);ctx.stroke();
      ctx.restore();
    });
    canvas.dataset.frames = String(Number(canvas.dataset.frames || 0)+1);
  }
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = last ? Math.min((now-last)/1000,.05) : 0;last=now;
    if (document.hidden || now-lastDraw < (width < 741 ? 32 : 16)) return;
    lastDraw=now;
    if (!paused) time += dt;
    if (paused) return;
    document.documentElement.style.setProperty('--journey-time',time.toFixed(3));
    if (cursorAllowed() && body.classList.contains('cursor-live')) {
      updateCursorFeedback();
      cursor.classList.toggle('is-hidden',pointerScene && document.querySelector('#scene-preview').classList.contains('controls-hidden'));
      cursorX+=(pointerX-cursorX)*.24;cursorY+=(pointerY-cursorY)*.24;
      placeCursor();
    }
    const chapterPhases = chapters.map(chapter => {
      const focalHeight = Math.min(chapter.height, height);
      return clamp((height * .52 - (chapter.top - scroll + focalHeight * .45)) / height, -1, 1);
    });
    if (introDone) blocks.forEach(block => {
      if(!block.active || block.element.matches(':focus-within')) return;
      const chapter = block.chapter;
      const position = chapter ? chapterPhases[chapter.index] : 0;
      const small = width < 741 ? .3 : 1;
      const drift = Math.sin(time * .45 + (chapter?.index || 0) * .25);
      block.element.style.setProperty('--drift-y',(position * -18 * small + drift * 1.4 * small).toFixed(2));
      block.element.style.setProperty('--drift-x',(px * 4 * small + position * block.direction * 6 * small).toFixed(2));
      block.element.style.setProperty('--depth-z',((14 + position * 10) * small).toFixed(2));
      block.element.style.setProperty('--depth-x',(position * 2.6 * small - py * .5 * small).toFixed(2));
      block.element.style.setProperty('--depth-y',(block.direction * .7 * small + px * 1.1 * small).toFixed(2));
    });
    track.style.transform=`translate3d(${-((time*36+scroll*.2)%920)}px,0,0)`;
    const footer=document.querySelector('.footer-wordmark');
    const footerTop=footer.getBoundingClientRect().top;
    if(footerTop<height)footer.style.setProperty('--footer-turn',String(clamp((footerTop-height*.4)/height*12,-6,10)));
    drawWorld();
    body.dataset.worldMotion='running';
  }
  requestAnimationFrame(frame);
})();
