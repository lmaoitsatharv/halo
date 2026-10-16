(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const body = document.body;
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const effectStage = $('#effect-stage');
  const effectHalo = effectStage.querySelector('.effect-halo');
  let effectStageVisible = true;
  let motionPaused = false;
  let demoPaused = false;
  let demoTime = 12;
  let toastTimer;
  let currentLine = -1;
  let currentWord = -1;
  let keyboardInteraction = false;
  document.addEventListener('keydown', () => { keyboardInteraction = true; }, true);
  document.addEventListener('pointerdown', () => { keyboardInteraction = false; }, true);
  const toast = message => {
    $('#toast').textContent = message;
    $('#toast').classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 4000);
  };

  // A missing project URL stays visibly pending; it never becomes a fake link.
  const repository = window.HALO_SITE?.repositoryUrl?.trim() || '';
  let validRepository = false;
  if (repository) {
    try {
      const url = new URL(repository);
      validRepository = url.protocol === 'https:' && url.hostname === 'github.com' && url.pathname.split('/').filter(Boolean).length >= 2;
    } catch { validRepository = false; }
  }
  if (validRepository) {
    $$('[data-repository]').forEach(link => {
      link.href = repository;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    });
    $$('[data-repository-pending]').forEach(element => element.hidden = true);
    $$('[data-repository-ready]').forEach(element => element.hidden = false);
    $$('[data-repository-label]').forEach(element => element.textContent = 'Explore Halo on GitHub');
    $('.nav-repo span').textContent = 'GitHub';
    const download = window.HALO_SITE?.downloadUrl?.trim() || '';
    try {
      const url = new URL(download);
      if (url.protocol === 'https:' && url.hostname === 'github.com' && url.pathname.endsWith('/Halo-Windows-x64.zip')) {
        $$('[data-download]').forEach(link => {
          link.href = url.href;
          link.removeAttribute('target');
          link.querySelector('[data-repository-label]').textContent = 'Download Windows ZIP';
        });
      }
    } catch { /* Keep the repository link if no valid app download is configured. */ }
  } else {
    $$('[data-repository]').forEach(link => {
      link.setAttribute('aria-describedby', 'repository-note');
      link.addEventListener('click', () => toast('The GitHub repository link is coming soon.'));
    });
  }

  const demoLines = [
    ['Leave', 'the', 'day', 'behind'],
    ['The', 'room', 'turns', 'to', 'gold.'],
    ['Stay', 'a', 'little', 'longer'],
    ['Light', 'finds', 'every', 'corner'],
    ['We', 'let', 'the', 'evening', 'in'],
    ['Hold', 'the', 'quiet', 'close']
  ];
  const lineText = index => demoLines[(index + demoLines.length) % demoLines.length].join(' ');
  const setIcon = (button, playing) => {
    button.querySelector('use').setAttribute('href', playing ? '#icon-pause' : '#icon-play');
    button.setAttribute('aria-pressed', String(!playing));
  };
  const updatePlayerButtons = () => {
    const playing = !demoPaused && !motionPaused && !motionPreference.matches;
    const labels = [[$('#hero-play'), 'visual demo'], [$('#lyric-play'), 'lyric illustration'], [$('#scene-play'), 'scene illustration']];
    labels.forEach(([button, label]) => {
      setIcon(button, playing);
      button.setAttribute('aria-label', `${playing ? 'Pause' : 'Play'} ${label}`);
    });
    body.classList.toggle('demo-paused', !playing);
  };
  const renderDemo = () => {
    const index = Math.floor(demoTime / 10) % demoLines.length;
    const words = demoLines[index];
    const word = Math.min(words.length - 1, Math.floor((demoTime % 10) / 10 * words.length));
    if (index !== currentLine) {
      if (currentLine !== -1 && !motionPaused && !motionPreference.matches) {
        ['.hero-lyrics', '.lyric-demo-lines', '.scene-words'].forEach(selector => {
          $(selector).animate([{ opacity: .55, translate: '0 6px' }, { opacity: 1, translate: '0 0' }], { duration: 650, easing: 'ease-out' });
        });
      }
      $('#hero-previous').textContent = lineText(index - 1);
      $('#hero-next').textContent = lineText(index + 1);
      const heroLine = $('#hero-current');
      heroLine.replaceChildren();
      const splitAt = Math.max(1, words.length - 2);
      heroLine.append(document.createTextNode(words.slice(0, splitAt).join(' ') + ' '), document.createElement('br'));
      if (words.length - splitAt > 1) heroLine.append(document.createTextNode(words.slice(splitAt, -1).join(' ') + ' '));
      const last = document.createElement('em');
      last.textContent = words.at(-1);
      heroLine.append(last);
      $('#lyric-line-before').textContent = lineText(index - 1);
      $('#lyric-line-after').textContent = lineText(index + 1);
      const lyricLine = $('#lyric-line-current');
      lyricLine.replaceChildren();
      words.forEach((text, i) => {
        const span = document.createElement('span');
        span.textContent = text;
        lyricLine.append(span);
        if (i < words.length - 1) lyricLine.append(document.createTextNode(' '));
      });
      const sceneLine = $('.scene-words>p');
      sceneLine.replaceChildren(document.createTextNode(words.slice(0, splitAt).join(' ') + ' '), document.createElement('br'));
      if (words.length - splitAt > 1) sceneLine.append(document.createTextNode(words.slice(splitAt, -1).join(' ') + ' '));
      const sceneLast = document.createElement('em');
      sceneLast.textContent = words.at(-1);
      sceneLine.append(sceneLast);
      $('.scene-previous').textContent = lineText(index - 1);
      $('.scene-next').textContent = lineText(index + 1);
      currentLine = index;
      currentWord = -1;
    }
    if (word !== currentWord) {
      $$('#lyric-line-current>span').forEach((span, i) => span.classList.toggle('active-word', i === word));
      currentWord = word;
    }
    $('#demo-time').textContent = `0:${String(Math.floor(demoTime)).padStart(2, '0')}`;
    $('#demo-progress').style.width = `${demoTime / 60 * 100}%`;
  };
  const toggleDemo = () => {
    if (motionPreference.matches) {
      toast('Reduced motion is enabled. Use the scene arrows to explore the original text.');
      return;
    }
    if (motionPaused) {
      motionPaused = false;
      updateMotion();
      demoPaused = false;
    } else demoPaused = !demoPaused;
    updatePlayerButtons();
  };
  [$('#hero-play'), $('#lyric-play'), $('#scene-play')].forEach(button => button.addEventListener('click', toggleDemo));

  // Visibility callbacks do not run when a motion control changes.
  const syncEffectMotion = () => {
    const paused = !effectStageVisible || motionPaused || motionPreference.matches || effectStage.dataset.mode === 'still';
    effectHalo.style.animationPlayState = paused ? 'paused' : '';
  };

  function updateMotion() {
    body.classList.toggle('motion-paused', motionPaused);
    body.classList.toggle('motion-reduced', motionPreference.matches);
    const paused = motionPaused || motionPreference.matches;
    const button = $('#motion-toggle');
    button.querySelector('span').textContent = motionPreference.matches ? 'Reduced motion' : paused ? 'Resume motion' : 'Pause motion';
    button.querySelector('use').setAttribute('href', paused ? '#icon-play' : '#icon-pause');
    button.setAttribute('aria-pressed', String(paused));
    button.setAttribute('aria-label', motionPreference.matches ? 'Reduced motion is enabled by your device' : paused ? 'Resume page motion' : 'Pause page motion');
    updatePlayerButtons();
    syncEffectMotion();
    if (paused) {
      $('#hero-installation').style.setProperty('--mx', '0');
      $('#hero-installation').style.setProperty('--my', '0');
    }
  }
  $('#motion-toggle').addEventListener('click', () => {
    if (motionPreference.matches) return toast('This page is using your device’s reduced-motion setting.');
    motionPaused = !motionPaused;
    updateMotion();
  });
  motionPreference.addEventListener('change', updateMotion);
  updateMotion();
  renderDemo();
  let lastTick = performance.now();
  setInterval(() => {
    const now = performance.now();
    const delta = Math.min((now - lastTick) / 1000, 1);
    lastTick = now;
    if (!document.hidden && !demoPaused && !motionPaused && !motionPreference.matches) {
      demoTime = (demoTime + delta) % 60;
      renderDemo();
    }
  }, 200);

  // Only original palette colours are used. No song, microphone or audio access.
  const palettes = [['#2450e8', '#f47b9b'], ['#f47b9b', '#ffd42a'], ['#4a63e8', '#ff94b3']];
  let paletteIndex = 0;
  setInterval(() => {
    if (document.hidden || motionPaused || motionPreference.matches) return;
    paletteIndex = (paletteIndex + 1) % palettes.length;
    document.documentElement.style.setProperty('--colour-one', palettes[paletteIndex][0]);
    document.documentElement.style.setProperty('--colour-two', palettes[paletteIndex][1]);
  }, 22000);

  const choose = (buttons, chosen) => buttons.forEach(button => {
    const selected = button === chosen;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  const effectDescriptions = {
    aura: ['Aura', 'A quiet wash of album-colour light.'],
    orbit: ['Orbit', 'A travelling highlight around a two-colour rim.'],
    wave: ['Wave', 'Colour ribbons, flowing around the screen.'],
    pulse: ['Pulse', 'A slow breath of light, with a soft inward glow.'],
    prism: ['Prism', 'A revolving spectrum drawn from the palette.']
  };
  $$('.effect-choice').forEach(button => button.addEventListener('click', () => {
    choose($$('.effect-choice'), button);
    $('#effect-stage').dataset.effect = button.dataset.effect;
    const [name, description] = effectDescriptions[button.dataset.effect];
    $('#effect-name').textContent = name;
    $('#effect-description').textContent = description;
  }));
  $$('.mode-picker button').forEach(button => button.addEventListener('click', () => {
    choose($$('.mode-picker button'), button);
    effectStage.dataset.mode = button.dataset.mode;
    syncEffectMotion();
    $('#light-demo-note').lastChild.textContent = button.dataset.mode === 'sync'
      ? ' Simulated loudness illustration. Halo follows system output loudness, not exact beats. This page does not listen to audio.'
      : ' Interactive illustration. In Halo, Music sync follows system output loudness, not exact beats.';
  }));
  $('#intensity').addEventListener('input', event => {
    const value = Number(event.target.value);
    $('#intensity-output').value = `${value}%`;
    $('#effect-stage').style.setProperty('--intensity', value / 100);
    event.target.style.background = `linear-gradient(to right, var(--green) ${(value - 20) / 80 * 100}%, #353c2b ${(value - 20) / 80 * 100}%)`;
  });
  let customPalette = false;
  const updatePalette = () => {
    $('#palette-toggle').setAttribute('aria-pressed', String(customPalette));
    $('#palette-label').textContent = customPalette ? 'Custom colours' : 'Album colours';
    $('#custom-colours').hidden = !customPalette;
    const stage = $('.light-experience');
    if (customPalette) {
      stage.style.setProperty('--colour-one', $('#colour-primary').value);
      stage.style.setProperty('--colour-two', $('#colour-secondary').value);
    } else {
      stage.style.removeProperty('--colour-one');
      stage.style.removeProperty('--colour-two');
    }
  };
  $('#palette-toggle').addEventListener('click', () => { customPalette = !customPalette; updatePalette(); });
  [$('#colour-primary'), $('#colour-secondary')].forEach(input => input.addEventListener('input', updatePalette));

  const styleDescriptions = {
    ship: 'A flowing wall of lyrics with a moving word spotlight.',
    fisheye: 'A kinetic word stack. The active word swells into focus.',
    'fisheye-visual': 'The word stack, with tilted colour strips and original symbols.',
    visual: 'One large word and symbol at a time, with soft transitions.'
  };
  $$('.lyric-picker button').forEach(button => button.addEventListener('click', () => {
    choose($$('.lyric-picker button'), button);
    $('#lyric-stage').dataset.style = button.dataset.style;
    $('#lyric-style-note').textContent = styleDescriptions[button.dataset.style];
  }));

  const scenes = {
    listening: ['Listening Room', 'Artwork, lyrics and soft light. Everything in its place.'],
    lyrics: ['Lyrics Only', 'The words, with the whole screen to themselves.'],
    cinema: ['Cinema', 'Just the atmosphere. A quiet song block in the bottom-left.'],
    orbit: ['Orbit', 'A little artwork, at the centre of its own universe.']
  };
  const scenePreview = $('#scene-preview');
  let controlsTimer;
  const revealControls = () => {
    scenePreview.classList.remove('controls-hidden');
    clearTimeout(controlsTimer);
    if (!motionPreference.matches && !scenePreview.classList.contains('keyboard-focus')) {
      controlsTimer = setTimeout(() => scenePreview.classList.add('controls-hidden'), 1500);
    }
  };
  $$('.scene-picker button').forEach(button => button.addEventListener('click', () => {
    choose($$('.scene-picker button'), button);
    scenePreview.dataset.scene = button.dataset.scene;
    $('#scene-title').textContent = scenes[button.dataset.scene][0];
    $('#scene-description').textContent = scenes[button.dataset.scene][1];
    revealControls();
  }));
  scenePreview.addEventListener('pointermove', revealControls);
  scenePreview.addEventListener('pointerenter', revealControls);
  scenePreview.addEventListener('pointerdown', revealControls);
  scenePreview.addEventListener('focusin', () => {
    scenePreview.classList.toggle('keyboard-focus', keyboardInteraction || scenePreview.classList.contains('expanded'));
    revealControls();
  });
  scenePreview.addEventListener('focusout', event => {
    if (!scenePreview.contains(event.relatedTarget)) scenePreview.classList.remove('keyboard-focus');
    revealControls();
  });
  motionPreference.addEventListener('change', revealControls);
  const seekLine = direction => {
    demoTime = ((Math.floor(demoTime / 10) + direction + demoLines.length) % demoLines.length) * 10;
    renderDemo();
    revealControls();
  };
  $('#scene-previous').addEventListener('click', () => seekLine(-1));
  $('#scene-next').addEventListener('click', () => seekLine(1));
  let focusBeforeExpand;
  const closeScene = () => {
    scenePreview.classList.remove('expanded');
    scenePreview.classList.toggle('keyboard-focus', keyboardInteraction);
    body.classList.remove('scene-expanded');
    scenePreview.removeAttribute('role');
    scenePreview.removeAttribute('aria-modal');
    $('#scene-expand').setAttribute('aria-label', 'Expand scene illustration');
    focusBeforeExpand?.focus();
  };
  $('#scene-expand').addEventListener('click', () => {
    if (scenePreview.classList.contains('expanded')) { closeScene(); return; }
    focusBeforeExpand = document.activeElement;
    scenePreview.classList.add('expanded');
    scenePreview.classList.add('keyboard-focus');
    body.classList.add('scene-expanded');
    scenePreview.setAttribute('role', 'dialog');
    scenePreview.setAttribute('aria-modal', 'true');
    $('#scene-expand').setAttribute('aria-label', 'Close expanded scene illustration');
    $('#scene-expand').focus();
    toast('Press Esc or use the corner control to return.');
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && scenePreview.classList.contains('expanded')) { event.preventDefault(); closeScene(); }
    if (!scenePreview.classList.contains('expanded')) return;
    if (event.key === 'Tab') {
      const focusable = [...scenePreview.querySelectorAll('button')].filter(element => getComputedStyle(element).display !== 'none' && element.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  scenePreview.addEventListener('keydown', event => {
    scenePreview.classList.add('keyboard-focus');
    revealControls();
    if (event.target.tagName === 'BUTTON') return;
    if (event.code === 'Space') { event.preventDefault(); toggleDemo(); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); seekLine(-1); }
    if (event.key === 'ArrowRight') { event.preventDefault(); seekLine(1); }
  });

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      effectStageVisible = entry.isIntersecting;
      syncEffectMotion();
    }), { rootMargin: '100px' });
    observer.observe(effectStage);
  }
})();
