# Halo website

Source for [halo-music-companion.vercel.app](https://halo-music-companion.vercel.app). This is a buildless static site. The Windows app source is in the repository's `halo/` folder; the ready-to-run Windows download is on [Releases](https://github.com/lmaoitsatharv/halo/releases/latest).

## Local preview

From the repository root:

```sh
python -m http.server 4173 --bind 127.0.0.1 --directory website
```

Open http://127.0.0.1:4173. Vercel injects its analytics endpoint only on deployments; that endpoint is not provided by this local static server.

`site-config.js` sets the repository and direct Windows ZIP links. Keep download links pointed at a published release asset. Demo visuals use original text and artwork, and do not access Spotify or listen to audio.

## Motion regression check

Install Playwright in a separate tools folder so it stays outside the published site:

```sh
npm install --prefix .staging/website-test-tools --no-save playwright@1.62.1
```

On Windows PowerShell, from the repository root:

```powershell
$env:NODE_PATH = "$PWD/.staging/website-test-tools/node_modules"
$env:HALO_BROWSER_CHANNEL = "msedge"
node tests/test_website_motion.cjs
# Or check a deployed copy:
node tests/test_website_motion.cjs https://halo-music-companion.vercel.app
```

The test uses an isolated browser and checks repeated pause/resume, frozen animation clocks, unrelated body-class changes while paused, keyboard and touch input, reduced motion, missing WebGL, nearby preview controls and direct download links. It fails if the page becomes unresponsive.

The pause fix makes the body's motion watcher respond only when the motion state changes. Cursor cleanup also removes the cursor class only when it exists. These checks prevent cursor cleanup from repeatedly triggering the same class observer.

## Deployment

Use `website` as the Vercel root directory with the **Other** framework preset. No build command is required. Link to the intended existing project, stage and test the production deployment before assigning its production domains. Do not commit `.vercel`, environment files or credentials.
