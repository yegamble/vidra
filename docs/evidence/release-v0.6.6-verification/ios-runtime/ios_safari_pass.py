#!/usr/bin/env python3
"""Focused real-iPhone Safari pass against the v0.6.6 stack via LambdaTest Tunnel.

What it proves (the iOS-specific risks desktop Chromium cannot): the watch page
loads on real iOS Safari through the tunnel, the <video> element reaches a
playable state and *advances* (native HLS on iOS), no media error, the player
is present; then a real sign-in through the login form. Everything else stays
with the desktop drills. Screenshots + a JSON result are written per step.

Usage: ios_safari_pass.py OUT_DIR  (env: LT_USERNAME, LT_ACCESS_KEY, LT_TUNNEL,
       VIDRA_ORIGIN, VIDRA_WATCH_PATH, VIDRA_VIDEO_ID, OWNER_JSON,
       LT_DEVICE, LT_IOS_VERSION)
"""
import json, os, sys, time, traceback
from pathlib import Path
from appium import webdriver
from appium.options.common import AppiumOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
origin = os.environ.get('VIDRA_ORIGIN', 'https://secure.video.test')
watch = os.environ.get('VIDRA_WATCH_PATH', '/v/BfnHVc4m9E4')
video_id = os.environ.get('VIDRA_VIDEO_ID', '')
owner = json.loads(Path(os.environ['OWNER_JSON']).read_text())
user, key = os.environ['LT_USERNAME'], os.environ['LT_ACCESS_KEY']
device = os.environ.get('LT_DEVICE', 'iPhone 15')
ios = os.environ.get('LT_IOS_VERSION', '17')
tunnel = os.environ.get('LT_TUNNEL', 'vidra-v066-ios')

result = {'status': 'UNVERIFIED', 'candidate': 'v0.6.6', 'device': device, 'ios': ios,
          'tunnel': tunnel, 'origin': origin, 'watch_path': watch, 'video_id': video_id,
          'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'checks': {}, 'steps': []}
def save():
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
def step(name, **kv):
    entry = {'step': name, 'at': time.strftime('%H:%M:%S', time.gmtime()), **kv}
    result['steps'].append(entry); save(); print(f'[ios] {name} {kv}', flush=True)

caps = {
    'platformName': 'iOS', 'browserName': 'Safari',
    'appium:deviceName': device, 'appium:platformVersion': ios,
    'appium:automationName': 'XCUITest',
    'lt:options': {'w3c': True, 'isRealMobile': True, 'tunnel': True, 'tunnelName': tunnel,
                   'build': 'vidra v0.6.6 iOS Safari pass', 'name': f'watch+signin {device} iOS {ios}',
                   'user': user, 'accessKey': key, 'autoAcceptAlerts': True, 'deviceOrientation': 'portrait',
                   'console': True, 'network': False},
}
opts = AppiumOptions().load_capabilities(caps)
hub = f'https://{user}:{key}@mobile-hub.lambdatest.com/wd/hub'
driver = None; phase = 'session'
try:
    driver = webdriver.Remote(hub, options=opts)
    result['session_id'] = driver.session_id
    step('session-created', session_id=driver.session_id, caps_device=device)
    wait = WebDriverWait(driver, 60)

    # --- 1) watch page loads over the tunnel ---
    phase = 'watch-page-loads'
    driver.get(origin + watch)
    wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')
    title = driver.title; url = driver.current_url
    (out / '01-watch.png').write_bytes(driver.get_screenshot_as_png())
    step(phase, title=title, url=url)
    result['checks'][phase] = 'PASS' if url.startswith(origin) else 'FAIL'

    # --- 2) native video element reaches playable state ---
    phase = 'video-element-ready'
    video = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'video')))
    ready = WebDriverWait(driver, 90).until(lambda d: d.execute_script(
        "const v=document.querySelector('video'); return v && v.readyState>=2 ? {ready:v.readyState, src:(v.currentSrc||v.src||'').slice(0,120), duration:v.duration} : null"))
    step(phase, **ready)
    result['checks'][phase] = 'PASS'

    # --- 3) playback advances (native HLS on iOS Safari) ---
    phase = 'playback-advances'
    start = driver.execute_script(
        "const v=document.querySelector('video'); v.muted=true; v.playsInline=true; const p=v.play(); return {t:v.currentTime, err:v.error?v.error.code:null}")
    def sample(d): return d.execute_script(
        "const v=document.querySelector('video'); return {t:v.currentTime, paused:v.paused, err:v.error?v.error.code:null, ready:v.readyState}")
    def advanced(d):
        s = sample(d)
        return s if (s['t'] - start['t']) >= 2 else None
    end = WebDriverWait(driver, 60).until(advanced)
    (out / '02-playing.png').write_bytes(driver.get_screenshot_as_png())
    step(phase, start=start, end=end)
    result['checks'][phase] = 'PASS' if end['err'] is None and end['t'] - start['t'] >= 2 else 'FAIL'
    result['playback'] = {'start': start, 'end': end, 'advanced_seconds': round(end['t'] - start['t'], 3)}

    # --- 4) real sign-in through the login form ---
    phase = 'sign-in'
    driver.get(origin + '/login')
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'form')))
    ident = driver.find_element(By.CSS_SELECTOR, "input[name='identifier'],input[type='email'],input[autocomplete='username']")
    pw = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
    ident.send_keys(owner['email']); pw.send_keys(owner['password'])
    (out / '03-login-filled.png').write_bytes(driver.get_screenshot_as_png())
    pw.submit()
    signed = WebDriverWait(driver, 60).until(lambda d: d.execute_script(
        "return !!(document.querySelector(\"[aria-label='Open account menu'],button[aria-label*='account' i]\")) || /\\/(studio|home|videos)?$/.test(location.pathname) || document.cookie.length>0"))
    (out / '04-signed-in.png').write_bytes(driver.get_screenshot_as_png())
    step(phase, url=driver.current_url, signed=signed)
    result['checks'][phase] = 'PASS' if signed else 'FAIL'

    result['status'] = 'PASS' if all(v == 'PASS' for v in result['checks'].values()) else 'FAIL'
except Exception as e:
    result['status'] = 'FAIL'; result['failed_phase'] = phase; result['error'] = traceback.format_exc()[-3000:]
    try:
        if driver: (out / f'99-fail-{phase}.png').write_bytes(driver.get_screenshot_as_png())
    except Exception: pass
finally:
    result['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    try:
        if driver:
            driver.execute_script(f'lambda-status={"passed" if result["status"]=="PASS" else "failed"}')
            driver.quit()
    except Exception: pass
    save()
    print(json.dumps({'status': result['status'], 'checks': result['checks'], 'failed_phase': result.get('failed_phase')}))
    sys.exit(0 if result['status'] == 'PASS' else 1)
