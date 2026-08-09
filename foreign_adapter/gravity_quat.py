"""Gravity-vector reconstruction from a CMAttitude quaternion.

Validated empirically against data_ege_sensorlogger_pipeline/E2_session6
(which carries both quaternion AND ground-truth gravityX/Y/Z from
CMDeviceMotion): mean abs error of gravity_from_quaternion() vs. the
recorded gravity vector is ~2e-8 (float noise) over 2000 samples.

Needed because data_ege_pipeline (the custom watchOS app) only exports
raw total acceleration + quaternion, not a separate gravity channel —
gravity has to be rotated out of the quaternion instead of measured
directly.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def gravity_from_quaternion(qx: np.ndarray, qy: np.ndarray, qz: np.ndarray, qw: np.ndarray) -> np.ndarray:
    """Rotate the world-frame "down" vector (0, 0, -1) into the device frame.

    Returns an (N, 3) array of unit-norm gravity vectors in device
    coordinates — matches the semantics of our own gx/gy/gz (motion.gravity).
    """
    quat = np.stack([qx, qy, qz, qw], axis=1)
    return Rotation.from_quat(quat).inv().apply([0.0, 0.0, -1.0])
