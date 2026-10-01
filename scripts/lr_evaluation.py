"""Probability metrics and host-cluster uncertainty for the LR experiment."""

import numpy as np
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                             confusion_matrix, log_loss, roc_auc_score)


def metrics(y, probability, hosts):
    if not len(y):
        return {"rows": 0}
    both = len(np.unique(y)) == 2
    host_aucs = []
    for host in np.unique(hosts):
        mask = hosts == host
        if len(np.unique(y[mask])) == 2:
            host_aucs.append(roc_auc_score(y[mask], probability[mask]))
    return {
        "rows": len(y), "hosts": len(np.unique(hosts)), "positive_rate": float(np.mean(y)),
        "roc_auc": float(roc_auc_score(y, probability)) if both else None,
        "average_precision": float(average_precision_score(y, probability)) if both else None,
        "log_loss": float(log_loss(y, probability, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y, probability)),
        "accuracy_at_0_5": float(accuracy_score(y, probability >= .5)),
        "confusion_matrix": confusion_matrix(y, probability >= .5, labels=[0, 1]).tolist(),
        "mean_within_host_auc": float(np.mean(host_aucs)) if host_aucs else None,
        "paired_hosts": len(host_aucs),
    }


def host_bootstrap(y, probability, hosts, repeats=500, seed=142):
    rng = np.random.default_rng(seed)
    unique = np.unique(hosts)
    groups = [np.flatnonzero(hosts == host) for host in unique]
    samples = {name: [] for name in ("roc_auc", "log_loss", "brier_score")}
    for _ in range(repeats):
        indices = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        yi, pi = y[indices], probability[indices]
        if len(np.unique(yi)) < 2:
            continue
        samples["roc_auc"].append(roc_auc_score(yi, pi))
        samples["log_loss"].append(log_loss(yi, pi, labels=[0, 1]))
        samples["brier_score"].append(brier_score_loss(yi, pi))
    return {name: {"low": float(np.quantile(values, .025)), "high": float(np.quantile(values, .975)), "replicates": len(values)} for name, values in samples.items()}
