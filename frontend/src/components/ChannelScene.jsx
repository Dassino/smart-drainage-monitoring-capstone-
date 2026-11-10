import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { CHANNEL, FLOOR_CM } from '../config'

// Scene units. 1 cm of water = PER_CM units, so the sensor (45.8 cm above the floor) stands 4.5 units high.
const PER_CM = 4.5 / 45.8
const L = 14          // channel length (flow runs left to right, node 1 upstream)
const W = 3.2         // channel width
const H = CHANNEL.maxDepthCm * PER_CM   // wall height
const X = { 1: -4.2, 2: 4.2 }
const SENSOR_Y = FLOOR_CM['1'] * PER_CM

const WATER_VERT = `
uniform float uH1; uniform float uH2; uniform float uTime; uniform float uAmp; uniform float uL;
varying float vTop; varying float vH; varying vec2 vXZ;
void main() {
  float u = (position.x + uL * 0.5) / uL;
  float h = mix(uH1, uH2, u);
  vec3 p = position;
  float top = step(0.0, p.y);
  float wave = (sin(p.x * 1.6 - uTime * 1.8) + sin(p.z * 2.3 + uTime * 1.3) * 0.6) * uAmp;
  p.y = top * (h + wave * step(0.02, h));
  vTop = top; vH = h; vXZ = vec2(p.x, p.z);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`

const WATER_FRAG = `
uniform float uTime; uniform float uSpeed; uniform vec3 uColor; uniform float uAlpha; uniform float uGrey;
varying float vTop; varying float vH; varying vec2 vXZ;
void main() {
  float streak = sin(vXZ.x * 2.6 + vXZ.y * 0.9 - uTime * uSpeed * 3.0);
  float s = smoothstep(0.82, 1.0, streak) * vTop * step(0.05, uSpeed);
  vec3 col = uColor * mix(0.9, 1.0, clamp(vH / 1.5, 0.0, 1.0)) + vec3(0.16) * s + vec3(0.05) * vTop;
  col = mix(col, vec3(dot(col, vec3(0.333))), uGrey);
  gl_FragColor = vec4(col, uAlpha);
}`

const COLORS = {
  Normal: new THREE.Color('#1aa3b0'),
  Blockage: new THREE.Color('#f5b21f'),
  Flood: new THREE.Color('#e5484d'),
}
const LED = { ONLINE: '#22c55e', STALE: '#f59e0b', OFFLINE: '#6b7280', 'NO DATA': '#6b7280' }

function sensorHead(id) {
  const g = new THREE.Group()
  const metal = new THREE.MeshStandardMaterial({ color: '#33474a', roughness: 0.5, metalness: 0.3 })
  // post beside the channel and an arm over it
  const post = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, SENSOR_Y + 0.6, 12), metal)
  post.position.set(0, (SENSOR_Y + 0.6) / 2, -(W / 2 + 0.5))
  const arm = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, W / 2 + 0.6), metal)
  arm.position.set(0, SENSOR_Y + 0.3, -(W / 2 + 0.5) + (W / 2 + 0.6) / 2)
  const housing = new THREE.Mesh(
    new THREE.BoxGeometry(0.9, 0.5, 0.9),
    new THREE.MeshStandardMaterial({ color: id === 1 ? '#0e7c86' : '#e8743b', roughness: 0.45 }),
  )
  housing.position.set(0, SENSOR_Y + 0.35, 0)
  const probe = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.22, 20), new THREE.MeshStandardMaterial({ color: '#101c1e' }))
  probe.position.set(0, SENSOR_Y + 0.0, 0)
  const ledMat = new THREE.MeshStandardMaterial({ color: LED.OFFLINE, emissive: LED.OFFLINE, emissiveIntensity: 1.2 })
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 16), ledMat)
  led.position.set(0.3, SENSOR_Y + 0.62, 0.46)
  g.add(post, arm, housing, probe, led)

  // beam from the probe down to the water surface
  const beamMat = new THREE.MeshBasicMaterial({ color: '#7fe3ee', transparent: true, opacity: 0.16, depthWrite: false, side: THREE.DoubleSide })
  const beam = new THREE.Mesh(new THREE.ConeGeometry(0.6, 1, 24, 1, true), beamMat)
  g.add(beam)
  return { group: g, ledMat, beam, beamMat }
}

export default function ChannelScene({ nodes, level, cls }) {
  const mountRef = useRef(null)
  const labelRefs = useRef({ 1: null, 2: null })
  const dataRef = useRef({ nodes, level, cls })
  const [failed, setFailed] = useState(false)
  dataRef.current = { nodes, level, cls }

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return undefined
    let renderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    } catch {
      setFailed(true)
      return undefined
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    mount.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100)
    camera.position.set(0.5, 6.2, 15.5)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.set(0, 2.1, 0)
    controls.enablePan = false
    controls.enableDamping = true
    controls.minDistance = 8
    controls.maxDistance = 24
    controls.maxPolarAngle = Math.PI / 2.05
    controls.update()

    scene.add(new THREE.HemisphereLight('#ffffff', '#9fb8b6', 1.5))
    const sun = new THREE.DirectionalLight('#ffffff', 1.4)
    sun.position.set(6, 10, 8)
    scene.add(sun)
    const alarm = new THREE.PointLight('#ff3b30', 0, 30)
    alarm.position.set(0, 5, 4)
    scene.add(alarm)

    // ground, base and walls
    const ground = new THREE.Mesh(new THREE.CircleGeometry(15, 64), new THREE.MeshStandardMaterial({ color: '#cfe0de', roughness: 1 }))
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.22
    scene.add(ground)
    const grid = new THREE.GridHelper(30, 30, '#9db8b5', '#b5cbc9')
    grid.position.y = -0.21
    grid.material.transparent = true
    grid.material.opacity = 0.35
    scene.add(grid)
    const base = new THREE.Mesh(new THREE.BoxGeometry(L + 0.4, 0.2, W + 0.5), new THREE.MeshStandardMaterial({ color: '#5d7776', roughness: 0.8 }))
    base.position.y = -0.1
    scene.add(base)
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(L, W), new THREE.MeshStandardMaterial({ color: '#b6a583', roughness: 1 }))
    floor.rotation.x = -Math.PI / 2
    floor.position.y = 0.005
    scene.add(floor)
    const wallMat = new THREE.MeshStandardMaterial({
      color: '#a6d3cf', transparent: true, opacity: 0.2, roughness: 0.2, emissive: '#000000', depthWrite: false,
    })
    const wallBack = new THREE.Mesh(new THREE.BoxGeometry(L, H, 0.1), wallMat)
    wallBack.position.set(0, H / 2, -(W / 2 + 0.05))
    const wallFront = new THREE.Mesh(new THREE.BoxGeometry(L, H, 0.1), wallMat)
    wallFront.position.set(0, H / 2, W / 2 + 0.05)
    wallBack.renderOrder = 3
    wallFront.renderOrder = 3
    scene.add(wallBack, wallFront)
    const rim = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(L, H, W + 0.2)),
      new THREE.LineBasicMaterial({ color: '#5d8583' }),
    )
    rim.position.y = H / 2
    scene.add(rim)

    // water
    const waterMat = new THREE.ShaderMaterial({
      vertexShader: WATER_VERT,
      fragmentShader: WATER_FRAG,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uH1: { value: 0 }, uH2: { value: 0 }, uTime: { value: 0 }, uAmp: { value: 0.02 }, uL: { value: L },
        uSpeed: { value: 0 }, uColor: { value: COLORS.Normal.clone() }, uAlpha: { value: 0.9 }, uGrey: { value: 0 },
      },
    })
    const water = new THREE.Mesh(new THREE.BoxGeometry(L, 1, W - 0.06, 80, 1, 10), waterMat)
    water.renderOrder = 1
    scene.add(water)

    // flow particles
    const N = 160
    const pPos = new Float32Array(N * 3)
    const pX = new Float32Array(N)
    const pZ = new Float32Array(N)
    for (let i = 0; i < N; i += 1) {
      pX[i] = (Math.random() - 0.5) * L
      pZ[i] = (Math.random() - 0.5) * (W - 0.5)
    }
    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3))
    const pMat = new THREE.PointsMaterial({ color: '#ffffff', size: 0.09, transparent: true, opacity: 0.85, depthWrite: false })
    const particles = new THREE.Points(pGeo, pMat)
    particles.renderOrder = 2
    scene.add(particles)

    // sensor nodes
    const heads = {}
    ;[1, 2].forEach((id) => {
      const h = sensorHead(id)
      h.group.position.x = X[id]
      scene.add(h.group)
      heads[id] = h
    })

    // animation state
    const cur = { h1: 0, h2: 0, f1: 0, f2: 0, speed: 0, grey: 0, color: COLORS.Normal.clone(), alarm: 0 }
    const target = new THREE.Color()
    const clock = new THREE.Clock()
    let raf = 0
    const tmp = new THREE.Vector3()

    const size = () => {
      const w = mount.clientWidth || 600
      const h = mount.clientHeight || 400
      renderer.setSize(w, h, false)
      renderer.domElement.style.width = '100%'
      renderer.domElement.style.height = '100%'
      camera.aspect = w / h
      camera.fov = camera.aspect < 0.9 ? 66 : camera.aspect < 1.4 ? 50 : camera.aspect < 2 ? 38 : 47   // wider view on narrow screens
      camera.updateProjectionMatrix()
    }
    size()
    const ro = new ResizeObserver(size)
    ro.observe(mount)

    const lerp = (a, b, k) => a + (b - a) * k

    const frame = () => {
      raf = requestAnimationFrame(frame)
      const dt = Math.min(clock.getDelta(), 0.1)
      const t = clock.elapsedTime
      const { nodes: nd, level: lv, cls: cl } = dataRef.current
      const k = 1 - Math.exp(-dt * 2.2)

      const live = (id) => nd?.[id]?.state === 'ONLINE'
      const depthOf = (id) => (nd?.[id]?.depth != null ? nd[id].depth : 0)
      const tgtH = (id) => {
        if (!live(id)) return cur[`h${id}`]                      // no live data: freeze, never invent a level
        const d = depthOf(id)
        return d < CHANNEL.dryBelowCm ? 0 : Math.min(d, CHANNEL.maxDepthCm * 1.04) * PER_CM
      }
      const tgtF = (id) => (live(id) && (nd?.[id]?.flow ?? 0) > CHANNEL.flowingAboveLpm ? nd[id].flow : 0)
      cur.h1 = lerp(cur.h1, tgtH(1), k)
      cur.h2 = lerp(cur.h2, tgtH(2), k)
      cur.f1 = lerp(cur.f1, tgtF(1), k)
      cur.f2 = lerp(cur.f2, tgtF(2), k)
      const anyLive = live(1) || live(2)
      const allLive = live(1) && live(2)
      cur.grey = lerp(cur.grey, allLive ? 0 : anyLive ? 0.35 : 0.85, k)
      cur.speed = lerp(cur.speed, Math.max(cur.f1, cur.f2) > 0 ? Math.min(2.4, 0.4 + (cur.f1 + cur.f2) * 0.25) : 0, k)

      // colour follows the diagnosis
      target.copy(COLORS[cl] ?? COLORS.Normal)
      cur.color.lerp(target, k)

      waterMat.uniforms.uTime.value = t
      waterMat.uniforms.uH1.value = cur.h1
      waterMat.uniforms.uH2.value = cur.h2
      waterMat.uniforms.uSpeed.value = cur.speed
      waterMat.uniforms.uAmp.value = cur.speed > 0 ? 0.015 + Math.min(0.03, cur.speed * 0.012) : 0.004
      waterMat.uniforms.uColor.value.copy(cur.color)
      waterMat.uniforms.uGrey.value = cur.grey
      water.visible = Math.max(cur.h1, cur.h2) > 0.02
      water.position.y = 0

      // particles ride the surface and move with the local flow
      const arr = pGeo.attributes.position.array
      for (let i = 0; i < N; i += 1) {
        const u = (pX[i] + L / 2) / L
        const h = lerp(cur.h1, cur.h2, u)
        const f = u < 0.5 ? cur.f1 : cur.f2
        pX[i] += Math.min(3.2, f * 0.7) * dt
        if (pX[i] > L / 2) pX[i] -= L
        arr[i * 3] = pX[i]
        arr[i * 3 + 1] = h > 0.04 && f > 0 ? h + 0.05 + Math.sin(t * 3 + i) * 0.01 : -50
        arr[i * 3 + 2] = pZ[i]
      }
      pGeo.attributes.position.needsUpdate = true

      // alarm light and wall tint
      const alertNow = lv === 'alert'
      cur.alarm = lerp(cur.alarm, alertNow ? 1 : lv === 'warning' ? 0.35 : 0, k)
      const pulse = alertNow ? 0.6 + 0.4 * Math.sin(t * 6) : 1
      alarm.intensity = cur.alarm * 70 * pulse
      wallMat.emissive.set(alertNow ? '#ff2a1f' : '#f59e0b')
      wallMat.emissiveIntensity = cur.alarm * 0.55 * pulse

      // sensor heads
      ;[1, 2].forEach((id) => {
        const hd = heads[id]
        const st = nd?.[id]?.state ?? 'NO DATA'
        const col = alertNow && st === 'ONLINE' ? '#ef4444' : LED[st] ?? LED.OFFLINE
        hd.ledMat.color.set(col)
        hd.ledMat.emissive.set(col)
        hd.ledMat.emissiveIntensity = st === 'ONLINE' ? 1.0 + 0.8 * Math.sin(t * (alertNow ? 8 : 3)) : 0.4
        const u = (X[id] + L / 2) / L
        const surf = lerp(cur.h1, cur.h2, u)
        const len = Math.max(0.05, SENSOR_Y - surf)
        hd.beam.scale.set(1, len, 1)
        hd.beam.position.y = SENSOR_Y - len / 2
        hd.beamMat.opacity = st === 'ONLINE' ? 0.14 + 0.05 * Math.sin(t * 4 + id) : 0
        hd.beam.visible = st === 'ONLINE'
      })

      // HTML labels follow the sensors
      const box = mount.getBoundingClientRect()
      ;[1, 2].forEach((id) => {
        const el = labelRefs.current[id]
        if (!el) return
        tmp.set(X[id], SENSOR_Y + 1.15, 0).project(camera)
        const x = (tmp.x * 0.5 + 0.5) * box.width
        const y = (-tmp.y * 0.5 + 0.5) * box.height
        el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`
      })

      controls.update()
      renderer.render(scene, camera)
    }
    frame()

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      controls.dispose()
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose()
        if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose())
      })
      renderer.dispose()
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
    }
  }, [])

  const stateText = { ONLINE: 'Online', STALE: 'Stale', OFFLINE: 'Offline', 'NO DATA': 'No data' }
  const stateCls = { ONLINE: 'ok', STALE: 'stale', OFFLINE: 'off', 'NO DATA': 'off' }

  return (
    <div className="scene" role="img" aria-label="Live 3D view of the drainage channel with node 1 and node 2">
      <div className="scene-gl" ref={mountRef} />
      {failed && (
        <div className="scene-fail">3D view unavailable in this browser (WebGL is off). The readings below are unaffected.</div>
      )}
      {[1, 2].map((id) => {
        const n = nodes?.[id]
        const st = n?.state ?? 'NO DATA'
        const wet = n?.depth != null && n.depth >= CHANNEL.dryBelowCm
        return (
          <div key={id} className="scene-label" ref={(el) => { labelRefs.current[id] = el }}>
            <div className="sl-head">
              <b>Node {id}</b>
              <span className="sl-role">{id === 1 ? 'upstream' : 'downstream'}</span>
              <span className={`badge ${stateCls[st] ?? 'off'}`}>{stateText[st] ?? '—'}</span>
            </div>
            {st === 'ONLINE' ? (
              <div className="sl-body">
                {wet ? `${n.depth.toFixed(1)} cm deep` : 'Dry'} · {n.flow > CHANNEL.flowingAboveLpm ? `${n.flow.toFixed(1)} L/min` : 'no flow'}
              </div>
            ) : (
              <div className="sl-body">No live data{n?.ageS != null ? ` · last seen ${fmtAge(n.ageS)}` : ''}</div>
            )}
          </div>
        )
      })}
      <div className="scene-flow" aria-hidden="true">flow direction &rarr;</div>
    </div>
  )
}

function fmtAge(s) {
  if (s < 60) return `${Math.round(s)} s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  return `${(s / 3600).toFixed(1)} h ago`
}
