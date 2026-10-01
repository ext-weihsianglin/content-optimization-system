"""Serializable PCA fits and separately labeled exploratory UMAP maps."""

import io
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors

from .runner import load_vectors, run_lock
from .storage import atomic_bytes, content_identity, digest, file_hash, read_json, read_rows, write_json, write_rows


def view_units(run, vectors, view, subview=None):
    return [u for u in read_rows(Path(run) / "units.parquet")
            if u["view"] == view and u["unit_id"] in vectors and not u["subview"].endswith(":chunk")
            and (subview is None or u["subview"].startswith(subview))]


def fit_pca(matrix, components, seed=42):
    if components < 1 or components > min(matrix.shape[1], len(matrix) - 1):
        raise ValueError("PCA components must fit feature count and sample rank")
    if not np.isfinite(matrix).all() or np.allclose(matrix, matrix[0]):
        raise ValueError("PCA requires finite, nonconstant training vectors")
    solver = "randomized" if len(matrix) >= 1000 else "full"
    pca = PCA(n_components=components, svd_solver=solver, whiten=False,
              random_state=seed, iterated_power=3)
    pca.fit(matrix)
    return pca


def project(run, model_name, view="page", components=32, *, fit_manifest=None, exploratory=False, umap=False, subview=None):
    run = Path(run)
    with run_lock(run):
        vectors, manifest = load_vectors(run, model_name)
        units = view_units(run, vectors, view, subview)
        lookup = {u["unit_id"]: u for u in units}
        if not units:
            raise ValueError("No successful vectors for requested view")
        if fit_manifest and exploratory:
            raise ValueError("Choose explicit training fit or exploratory scope")
        if not fit_manifest and not exploratory:
            raise ValueError("Supply --fit-manifest, or explicitly select --exploratory")
        if umap and not exploratory:
            raise ValueError("UMAP is restricted to labeled exploratory maps")
        if fit_manifest:
            fit = read_json(fit_manifest)
            fit_ids = fit["unit_ids"]
            heldout = fit.get("heldout_unit_ids", [])
            if fit.get("scope") != "training" or len(set(fit_ids)) != len(fit_ids) or not fit_ids:
                raise ValueError("Training manifest must contain unique nonempty fit IDs")
            if set(fit_ids) & set(heldout) or not set(fit_ids + heldout) <= set(lookup):
                raise ValueError("Unknown or overlapping training/held-out IDs")
            associations = read_rows(run / "associations.parquet")
            hosts = {}
            for row in associations:
                hosts.setdefault(row["snapshot_id"], set()).add(row["hostname"])
                hosts.setdefault(row["query_unit_id"], set()).add(row["hostname"])
            def unit_hosts(uid):
                return hosts.get(lookup[uid]["snapshot_id"] or uid, set())
            train_hosts = set().union(*(unit_hosts(uid) for uid in fit_ids))
            test_hosts = set().union(*(unit_hosts(uid) for uid in heldout))
            if train_hosts & test_hosts:
                raise ValueError("Training/held-out hostnames overlap")
            all_units = {u["unit_id"]: u for u in read_rows(run / "units.parquet")}
            train_hashes = {content_identity(lookup[uid], all_units) for uid in fit_ids}
            if train_hashes & {content_identity(lookup[uid], all_units) for uid in heldout}:
                raise ValueError("Training/held-out duplicate content")
        else:
            fit_ids = sorted(lookup)
        matrix = np.stack([vectors[uid] for uid in fit_ids])
        pca = fit_pca(matrix, components, manifest["configuration"]["seed"])
        del matrix
        all_ids = sorted(lookup)
        full = np.stack([vectors[uid] for uid in all_ids])
        transformed = pca.transform(full)
        if not umap:
            del full
        metadata = {"model_config_id": manifest["models"][model_name]["config_id"], "view": view,
                    "subview": subview, "solver": pca.svd_solver, "iterated_power": pca.iterated_power,
                    "serializer_version": manifest["serializer_version"],
                    "seed": manifest["configuration"]["seed"], "umap_requested": umap,
                    "scope": "exploratory_all_available" if exploratory else "training",
                    "fit_unit_ids": fit_ids, "components": components, "whiten": False,
                    "input_normalization": "l2", "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
                    "vector_hash": manifest["artifacts"][f"vectors/{manifest['models'][model_name]['config_id']}/vectors.npy"]}
        from importlib.metadata import version
        metadata["dependencies"] = {name: version(name) for name in ("numpy", "scikit-learn")}
        identity = digest(metadata)
        folder = run / "projections" / identity
        stream = io.BytesIO()
        np.savez(stream, mean=pca.mean_, components=pca.components_)
        atomic_bytes(folder / "pca.npz", stream.getvalue())
        write_rows(folder / "pca.parquet", [{"unit_id": uid, "coordinates": coords.tolist()} for uid, coords in zip(all_ids, transformed)])
        if umap:
            if len(full) < 4:
                raise ValueError("UMAP requires at least four available units")
            from umap import UMAP
            seed = manifest["configuration"]["seed"]
            neighbors = min(15, len(full) - 1)
            mapper = UMAP(n_neighbors=neighbors, n_components=2, metric="cosine", random_state=seed, n_jobs=1, init="random")
            coordinates = mapper.fit_transform(full)
            original_neighbors = NearestNeighbors(n_neighbors=min(6, len(full)), metric="cosine").fit(full).kneighbors(full, return_distance=False)
            screen_neighbors = NearestNeighbors(n_neighbors=min(6, len(full))).fit(coordinates).kneighbors(coordinates, return_distance=False)
            overlap = [len((set(a) - {i}) & (set(b) - {i})) / max(1, len(set(a) - {i})) for i, (a, b) in enumerate(zip(original_neighbors, screen_neighbors))]
            write_rows(folder / "umap.parquet", [{"unit_id": uid, "x": float(xy[0]), "y": float(xy[1]),
                          "neighbor_unit_ids": [all_ids[j] for j in original_neighbors[i] if j != i]}
                         for i, (uid, xy) in enumerate(zip(all_ids, coordinates))])
            metadata["umap"] = {"seed": seed, "neighbors": neighbors, "metric": "cosine", "scope": "exploratory_all_available",
                                "mean_neighbor_overlap_at_5": float(np.mean(overlap)), "dependency": version("umap-learn")}
        write_json(folder / "metadata.json", metadata)
        manifest.setdefault("projections", {})[identity] = {"path": str(folder.relative_to(run)), **metadata}
        for filename in ("pca.npz", "pca.parquet", "metadata.json", *( ["umap.parquet"] if umap else [])):
            relative = str((folder / filename).relative_to(run))
            manifest["artifacts"][relative] = file_hash(run / relative)
        write_json(run / "manifest.json", manifest)
        return {"projection_id": identity, "units": len(all_ids), "fit_units": len(fit_ids), "scope": metadata["scope"]}


def apply_pca(run, model_name, projection_folder, output):
    vectors, manifest = load_vectors(run, model_name)
    folder = Path(projection_folder)
    metadata = read_json(folder / "metadata.json")
    if metadata["model_config_id"] != manifest["models"][model_name]["config_id"]:
        raise ValueError("Projection model configuration is incompatible")
    if metadata["serializer_version"] != manifest["serializer_version"]:
        raise ValueError("Projection serializer is incompatible")
    fitted = np.load(folder / "pca.npz", allow_pickle=False)
    units = view_units(run, vectors, metadata["view"], metadata.get("subview"))
    coords = (np.stack([vectors[u["unit_id"]] for u in units]) - fitted["mean"]) @ fitted["components"].T
    write_rows(output, [{"unit_id": u["unit_id"], "coordinates": xy.tolist()} for u, xy in zip(units, coords)])
