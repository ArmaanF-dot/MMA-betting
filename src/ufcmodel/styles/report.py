"""Phase 5 report: discovered styles, stability, and the label template for Armaan."""
from pathlib import Path

from ufcmodel.features.asof import AXES, GROUPS, build_features, load_raw
from ufcmodel.styles.archetypes import describe_clusters, fit_style_model, add_style_matrix, stability, style_labels_template


def build(con, md_path, template_path) -> str:
    raw, statics = load_raw(con)
    rows = build_features(raw, statics)
    model = fit_style_model(rows)
    add_style_matrix(rows, model)
    names = dict(con.execute("SELECT fighter_id, name FROM fighters").fetchall())
    st = stability(rows, model)
    style_labels_template(rows, names, template_path)
    L = ["# Phase 5: style system", "",
         f"Each fighter-bout has {len(AXES)} as-of style axes (opponent-adjusted, shrunk to the global rate): " + ", ".join(AXES) + ".", "",
         "## Discovered styles (diagonal Gaussian mixture, 6 components, fit once on pre-2015 bouts)", ""]
    L += [f"- {line}" for line in describe_clusters(model)]
    L += ["", "## Stability", "",
          f"Bootstrap refits (20) on {st['n']} pre-2015 fighter snapshots: mean adjusted Rand index vs the reference clustering "
          f"{st['mean_ari']:.2f} (worst {st['min_ari']:.2f}). Agreement between the mixture and NMF clustering: {st['gmm_vs_nmf_ari']:.2f}. "
          "1.0 would be identical partitions; these are moderate, so treat style weights as soft descriptions, not hard labels.", "",
          "## Interaction terms and the ablation", "",
          f"Groups tested in the ablation (docs/phase10_evaluation.md): style_axes ({', '.join(GROUPS['style_axes'])}), "
          f"style_interactions ({', '.join(GROUPS['style_interactions'])}) and style_matrix (the 15 antisymmetric terms s_A[i] s_B[j] - s_A[j] s_B[i]). "
          "Each stays only if its interval is above zero there; the decisions are logged in docs/decisions.md.", "",
          "## Not done", "",
          "- Matching clusters to the 16 named archetypes and the semi-supervised placement need Armaan's labels for about 50 fighters: "
          f"`docs/{Path(template_path).name}` is ready with the model's own weights for the 50 fighters with the most bouts and a blank column to fill.",
          "- Tag-only axes (takedown setup, entry type, pressure vs counter, weapon mix) and the habits catalogue need the tagging programme.", ""]
    text = "\n".join(L)
    open(md_path, "w", encoding="utf-8").write(text)
    return text
