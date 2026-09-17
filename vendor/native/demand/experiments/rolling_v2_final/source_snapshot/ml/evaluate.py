import numpy as np

def predictions(model, x):
    """Evaluation and serving use identical nonnegative integer predictions."""
    return np.rint(np.maximum(0, model.predict(x))).astype(int)

def metrics(y, pred):
    y, pred = np.asarray(y, dtype=float), np.asarray(pred, dtype=float)
    if y.size == 0 or y.shape != pred.shape or not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise ValueError('Evaluation needs equal-length finite, nonempty arrays')
    error = pred - y
    nonzero = y != 0
    return dict(mae=float(np.abs(error).mean()), rmse=float(np.sqrt(np.square(error).mean())),
                mape_pct=float((np.abs(error[nonzero] / y[nonzero])).mean() * 100) if nonzero.any() else None,
                mape_excluded_zeros=int((~nonzero).sum()), n=len(y))

def monitoring(history, deterioration_ratio=1.25, min_recent=30):
    if history.empty:
        return dict(count=0, overall_mae=None, recent_30_mae=None, recent_60_mae=None,
                    baseline_mae=None, retraining_needed=False, reason='No actual results')
    d = history.sort_values('date')
    err = (d.actual_diners - d.predicted_diners).abs()
    prior = err.iloc[:-30]
    recent = float(err.tail(30).mean())
    baseline = float(prior.mean()) if len(prior) >= min_recent else None
    return dict(count=len(d), overall_mae=float(err.mean()), recent_30_mae=recent,
                recent_60_mae=float(err.tail(60).mean()), baseline_mae=baseline,
                recent_30_count=min(len(d), 30), recent_60_count=min(len(d), 60),
                retraining_needed=bool(baseline is not None and recent > baseline * deterioration_ratio),
                reason='Compare latest 30 with preceding history (at least 30 preceding rows); mixed-version operational metric')
