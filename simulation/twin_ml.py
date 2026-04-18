"""
simulation/twin_ml.py — ML Correction Layer for Digital Twin

Architecture
------------
RandomForestRegressor trained on data.csv to learn the residual
between the formula's predicted output and the actual Actual_Order_Qty.

At inference:
    correction = RF.predict(features) / max(formula_output, 1)
    adjusted   = formula_output × clip(correction, 0.7, 1.3)

Falls back silently to formula-only if model is not yet trained.

Model persistence: models/twin_model.pkl
"""

import logging
import os
import pickle
import threading
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_PATH = os.path.join(_ROOT_DIR, "models", "twin_model.pkl")
_DATA_PATH  = os.path.join(_ROOT_DIR, "data.csv")

# ── Singleton model cache ─────────────────────────────────────────────────────
_model_lock  = threading.Lock()
_model_cache = {
    "model":          None,
    "facility_enc":   {},   # facility_name → int
    "r2_score":       None,
    "feature_importances": {},
    "trained":        False,
    "training":       False,
    "error":          None,
}

# ── Features used ─────────────────────────────────────────────────────────────
# Must match exactly when building inference vectors.
_FEATURE_COLS = [
    "oee_pct",
    "workforce_pct",
    "energy_price",
    "downtime_hrs",
    "base_capacity",
    "demand_buffer_pct",
    "peak_ratio",
    "facility_enc",
]


# ── Public API ─────────────────────────────────────────────────────────────────

def get_model_status() -> dict:
    """Return current model state for the /api/twin/model/status endpoint."""
    with _model_lock:
        return {
            "trained":              _model_cache["trained"],
            "training":             _model_cache["training"],
            "r2_score":             _model_cache["r2_score"],
            "feature_importances":  _model_cache["feature_importances"],
            "error":                _model_cache["error"],
            "model_path":           _MODEL_PATH,
        }


def ensure_model_trained(data_csv: str = _DATA_PATH, force: bool = False):
    """
    Non-blocking: check if model exists / is trained. If not, train in a
    background thread. Called once at startup.
    """
    with _model_lock:
        if _model_cache["trained"] and not force:
            return
        if _model_cache["training"]:
            return
        _model_cache["training"] = True

    t = threading.Thread(target=_train_and_save, args=(data_csv,), daemon=True)
    t.start()
    logger.info("[TwinML] Background training thread started.")


def get_correction_factor(
    facility:       str,
    oee_pct:        float,
    workforce_pct:  float,
    energy_price:   float,
    downtime_hrs:   float,
    base_capacity:  int,
    demand_buffer_pct: float,
    peak_ratio:     float,
    formula_output: float,
) -> tuple[float, float]:
    """
    Returns (correction_factor, confidence) where:
        correction_factor ∈ [0.70, 1.30]
        confidence        ∈ [0.0, 1.0]

    If model is not ready, returns (1.0, 0.0) — no correction applied.
    """
    with _model_lock:
        model = _model_cache.get("model")
        enc   = _model_cache.get("facility_enc", {})
        r2    = _model_cache.get("r2_score") or 0.0

    if model is None:
        return 1.0, 0.0

    fac_int = enc.get(facility, enc.get("__unknown__", 0))
    X = np.array([[
        oee_pct,
        workforce_pct,
        energy_price,
        downtime_hrs,
        base_capacity,
        demand_buffer_pct,
        peak_ratio,
        fac_int,
    ]], dtype=float)

    try:
        ml_pred = float(model.predict(X)[0])
        raw_correction = ml_pred / max(formula_output, 1.0)
        correction = float(np.clip(raw_correction, 0.70, 1.30))
        confidence  = min(1.0, max(0.0, float(r2)))
        return correction, confidence
    except Exception as exc:
        logger.warning("[TwinML] Inference failed: %s", exc)
        return 1.0, 0.0


# ── Training ───────────────────────────────────────────────────────────────────

def _train_and_save(data_csv: str):
    """Full training pipeline. Runs in a background thread."""
    try:
        logger.info("[TwinML] Loading %s for training...", data_csv)
        df = _load_training_data(data_csv)
        if df is None or df.empty:
            raise ValueError("No training data available.")

        X, y, enc = _build_features(df)
        if len(X) < 20:
            raise ValueError(f"Too few training samples: {len(X)}")

        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import r2_score

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.20, random_state=42
        )

        model = RandomForestRegressor(
            n_estimators=120,
            max_depth=12,
            min_samples_split=4,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        r2 = float(r2_score(y_test, y_pred))
        logger.info("[TwinML] Training complete. R²=%.3f on %d samples.", r2, len(X))

        # Feature importances
        fi = {
            col: round(float(imp), 4)
            for col, imp in zip(_FEATURE_COLS, model.feature_importances_)
        }

        # Save to disk
        os.makedirs(os.path.dirname(_MODEL_PATH), exist_ok=True)
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump({"model": model, "facility_enc": enc, "r2": r2, "fi": fi}, f)

        with _model_lock:
            _model_cache["model"]          = model
            _model_cache["facility_enc"]   = enc
            _model_cache["r2_score"]       = r2
            _model_cache["feature_importances"] = fi
            _model_cache["trained"]        = True
            _model_cache["training"]       = False
            _model_cache["error"]          = None

        logger.info("[TwinML] Model saved to %s", _MODEL_PATH)

    except Exception as exc:
        logger.error("[TwinML] Training failed: %s", exc, exc_info=True)
        with _model_lock:
            _model_cache["training"] = False
            _model_cache["error"]    = str(exc)

        # Try to load existing model if training failed
        _try_load_existing()


def _try_load_existing():
    """If a pre-trained model exists on disk, load it into the cache."""
    if not os.path.exists(_MODEL_PATH):
        return
    try:
        with open(_MODEL_PATH, "rb") as f:
            bundle = pickle.load(f)
        with _model_lock:
            _model_cache["model"]          = bundle["model"]
            _model_cache["facility_enc"]   = bundle["facility_enc"]
            _model_cache["r2_score"]       = bundle.get("r2", None)
            _model_cache["feature_importances"] = bundle.get("fi", {})
            _model_cache["trained"]        = True
            _model_cache["training"]       = False
        logger.info("[TwinML] Loaded existing model from %s", _MODEL_PATH)
    except Exception as exc:
        logger.warning("[TwinML] Could not load existing model: %s", exc)


def _load_training_data(csv_path: str) -> Optional[pd.DataFrame]:
    """Load and group data.csv into daily per–facility rows."""
    try:
        df = pd.read_csv(csv_path, parse_dates=["Timestamp"])
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df = df.dropna(subset=["Timestamp"])

        numeric_cols = [
            "Actual_Order_Qty", "Machine_OEE_Pct",
            "Workforce_Deployed", "Workforce_Required",
            "Energy_Consumed_kWh", "Raw_Material_Inventory_Units",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df["date"]     = df["Timestamp"].dt.date
        df["is_peak"]  = df.get("Grid_Pricing_Period", pd.Series(dtype=str)).str.lower() == "peak"

        # Aggregate to daily per-facility
        grp = df.groupby(["Assigned_Facility", "date"])
        daily = grp.agg(
            actual_output    = ("Actual_Order_Qty",          "sum"),
            oee_pct          = ("Machine_OEE_Pct",           "mean"),
            workforce_dep    = ("Workforce_Deployed",         "sum"),
            workforce_req    = ("Workforce_Required",         "sum"),
            energy_kwh       = ("Energy_Consumed_kWh",        "sum"),
            peak_count       = ("is_peak",                    "sum"),
            row_count        = ("Actual_Order_Qty",           "count"),
        ).reset_index()

        # Derived features
        daily["workforce_pct"]  = np.where(
            daily["workforce_req"] > 0,
            daily["workforce_dep"] / daily["workforce_req"] * 100,
            95.0,
        )
        daily["peak_ratio"]      = daily["peak_count"] / daily["row_count"].clip(lower=1)
        daily["energy_price"]    = np.where(
            daily["peak_ratio"] > 0.5, 0.22, 0.09
        )
        # Approximate base_capacity as the plant's mean daily output
        plant_capacity           = daily.groupby("Assigned_Facility")["actual_output"].mean()
        daily["base_capacity"]   = daily["Assigned_Facility"].map(plant_capacity)
        daily["downtime_hrs"]    = 0.0
        daily["demand_buffer_pct"] = 0.10

        daily = daily[daily["actual_output"] > 0].reset_index(drop=True)
        return daily
    except Exception as exc:
        logger.error("[TwinML] _load_training_data failed: %s", exc)
        return None


def _build_features(df: pd.DataFrame):
    """Build X, y arrays and facility encoder."""
    facilities = sorted(df["Assigned_Facility"].unique())
    enc        = {fac: i for i, fac in enumerate(facilities)}
    enc["__unknown__"] = len(facilities)

    df = df.copy()
    df["facility_enc"] = df["Assigned_Facility"].map(enc)

    feature_df = df[[
        "oee_pct", "workforce_pct", "energy_price",
        "downtime_hrs", "base_capacity", "demand_buffer_pct",
        "peak_ratio", "facility_enc",
    ]].fillna(0)

    X = feature_df.values.astype(float)
    y = df["actual_output"].values.astype(float)
    return X, y, enc


# ── On import: try loading existing model from disk ───────────────────────────
_try_load_existing()
