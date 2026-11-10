// Settings for the live view. Change these to match the rig.
export const BRAND = { name: 'Smart Drainage Monitor', tagline: 'Flood early warning for urban drains' }

// Distance from each sensor to the dry channel floor (cm). Depth = floor distance - measured distance.
export const FLOOR_CM = { '1': 45.76, '2': 45.8 }

export const CHANNEL = {
  maxDepthCm: 25,        // water height drawn as a full channel. Set this to the real wall height of your channel.
  dryBelowCm: 0.7,       // below this depth the channel is drawn dry
  flowingAboveLpm: 0.1,  // below this flow the water is drawn still
  readingEveryS: 8.5,    // seconds between readings, used for the "alert in about" estimate
}

export const depthFromDistance = (node, dist) =>
  dist == null ? null : Math.max(0, (FLOOR_CM[node] ?? FLOOR_CM['1']) - dist)
