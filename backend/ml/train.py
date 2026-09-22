"""
train.py - trains the statute-identification model on the uploaded dataset and
builds the statute retrieval index used by the legal engine.

Two artefacts are produced:

1. clf_pipeline.joblib   TF-IDF (word 1-2 gram) + calibrated LinearSVC, trained on
                         case_facts -> ipc_section. This is the "evidence" signal:
                         it has seen 40k real judgments, but those judgments are long
                         and formal while a spoken complaint is short and colloquial,
                         so it is blended at a modest weight rather than trusted alone.

2. retrieval_index.joblib TF-IDF vectoriser fitted over one document per provision
                         (offence title x3 + statute body + keywords). Cosine similarity
                         between a complaint and these documents is the semantic signal.
                         This one handles short complaint text well.

Run:  python backend/ml/train.py --csv /path/to/indian_ipc_statute_identification.csv
"""
import argparse
import json
import os
import sys
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, top_k_accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
ART = os.path.join(HERE, "artifacts")

MIN_SAMPLES = 100  # a class needs this many judgments to be learnable


def clean(text: str) -> str:
    """Strip court boilerplate so the model learns facts, not headers."""
    import re
    t = str(text)
    t = re.sub(r"\[STATUTE\]", " ", t)                     # the label is masked in the corpus
    t = re.sub(r"={3,}|-{3,}|_{3,}", " ", t)
    t = re.sub(r"\b(IN THE HIGH COURT OF JUDICATURE AT|IN THE SUPREME COURT OF INDIA|"
               r"CORAM|ORAL ORDER|JUDGMENT|ORDER|HONOURABLE|HON'BLE|MR\. JUSTICE|"
               r"MRS\. JUSTICE|Criminal Miscellaneous No|Criminal Appeal No|"
               r"Petitioner|Opposite Party|Respondent|versus|Versus)\b", " ", t, flags=re.I)
    t = re.sub(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", " ", t)  # dates
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.environ.get("IPC_CSV", ""))
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    ap.add_argument("--max-features", type=int, default=60_000)
    args = ap.parse_args()

    if not args.csv or not os.path.exists(args.csv):
        sys.exit("CSV not found. Pass --csv /path/to/indian_ipc_statute_identification.csv")

    os.makedirs(ART, exist_ok=True)
    t0 = time.time()

    # ---------------------------------------------------------------- classifier
    print("Loading dataset ...")
    df = pd.read_csv(args.csv, usecols=["case_facts", "ipc_section"])
    df["ipc_section"] = df["ipc_section"].astype(str).str.strip()

    counts = df["ipc_section"].value_counts()
    keep = counts[counts >= args.min_samples].index
    kept = df[df["ipc_section"].isin(keep)].copy()
    print(f"  {len(df):,} rows -> {len(kept):,} rows across {len(keep)} classes "
          f"(classes with >= {args.min_samples} examples)")

    print("Cleaning court boilerplate ...")
    kept["text"] = kept["case_facts"].map(clean)

    X_train, X_test, y_train, y_test = train_test_split(
        kept["text"], kept["ipc_section"], test_size=0.2,
        random_state=42, stratify=kept["ipc_section"]
    )

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(
            sublinear_tf=True, ngram_range=(1, 2), min_df=3, max_df=0.6,
            max_features=args.max_features, strip_accents="unicode",
            stop_words="english",
        )),
        # ensemble=False calibrates via cross_val_predict and then keeps ONE fitted
        # estimator instead of one per fold. With 60 classes that is the difference
        # between a 98 MB artifact and an 8 MB one, at no measurable cost in accuracy.
        ("clf", CalibratedClassifierCV(
            LinearSVC(C=0.5, class_weight="balanced"), cv=3, method="sigmoid",
            ensemble=False,
        )),
    ])

    print("Training TF-IDF + calibrated LinearSVC ...")
    pipeline.fit(X_train, y_train)

    print("Evaluating ...")
    proba = pipeline.predict_proba(X_test)
    classes = pipeline.named_steps["clf"].classes_
    pred = classes[np.argmax(proba, axis=1)]
    top1 = accuracy_score(y_test, pred)
    top3 = top_k_accuracy_score(y_test, proba, k=3, labels=classes)
    top5 = top_k_accuracy_score(y_test, proba, k=5, labels=classes)
    print(f"  top-1 {top1:.3f} | top-3 {top3:.3f} | top-5 {top5:.3f}")

    # float64 coefficients buy nothing here and double the artifact size
    for calibrated in getattr(pipeline.named_steps["clf"], "calibrated_classifiers_", []):
        estimator = getattr(calibrated, "estimator", None)
        if estimator is not None and hasattr(estimator, "coef_"):
            estimator.coef_ = estimator.coef_.astype("float32")
            estimator.intercept_ = estimator.intercept_.astype("float32")

    joblib.dump(pipeline, os.path.join(ART, "clf_pipeline.joblib"), compress=3)
    size_mb = os.path.getsize(os.path.join(ART, "clf_pipeline.joblib")) / 1e6
    print(f"  artifact size {size_mb:.1f} MB")

    metrics = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": os.path.basename(args.csv),
        "n_rows_total": int(len(df)),
        "n_rows_used": int(len(kept)),
        "n_classes": int(len(keep)),
        "min_samples_per_class": args.min_samples,
        "top1_accuracy": round(float(top1), 4),
        "top3_accuracy": round(float(top3), 4),
        "top5_accuracy": round(float(top5), 4),
        "note": "Measured on a held-out 20% split of court judgments. A spoken citizen "
                "complaint is a different text domain, so this figure is an upper bound "
                "on in-app behaviour. The legal engine therefore blends this signal with "
                "statute retrieval and an explainable rule layer.",
    }
    with open(os.path.join(ART, "metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=2)

    # ------------------------------------------------------- category classifier
    # The section model predicts one of 60 exact sections, but at runtime the
    # element layer is what separates 379 from 380 from 381 - that part of the
    # prediction is discarded and recomputed from `dwelling`, `servant` and so on.
    # So the model is being scored on a distinction the system never uses.
    #
    # This second model predicts the offence *category* instead: fewer classes,
    # far more examples each, and it answers the same question the rule layer
    # answers, which makes it a genuine second opinion rather than a weak vote on
    # a question nothing else asks.
    print("\nTraining category classifier ...")
    with open(os.path.join(DATA, "crime_rules.json"), encoding="utf-8") as fh:
        rules_for_map = json.load(fh)

    section_to_category = {}
    for category in rules_for_map["categories"]:
        for provision in category["provisions"]:
            number = str(provision["code"]).split(":")[-1].strip()
            section_to_category.setdefault(number, category["id"])

    kept["category"] = kept["ipc_section"].map(section_to_category)
    cat_rows = kept[kept["category"].notna()].copy()
    cat_counts = cat_rows["category"].value_counts()
    cat_rows = cat_rows[cat_rows["category"].isin(cat_counts[cat_counts >= 50].index)]
    print(f"  {len(cat_rows):,} rows map to a known category "
          f"({cat_rows['category'].nunique()} categories, "
          f"{len(kept) - len(cat_rows):,} rows have no mapped category)")

    cat_metrics = {"trained": False,
                   "note": "Not enough mapped rows to train a category model."}
    if cat_rows["category"].nunique() >= 3 and len(cat_rows) >= 300:
        cX_train, cX_test, cy_train, cy_test = train_test_split(
            cat_rows["text"], cat_rows["category"], test_size=0.2,
            random_state=42, stratify=cat_rows["category"])

        cat_pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2),
                                      min_df=3, max_df=0.6, stop_words="english",
                                      max_features=args.max_features)),
            ("clf", CalibratedClassifierCV(
                LinearSVC(C=0.5, class_weight="balanced"),
                cv=3, method="sigmoid", ensemble=False)),
        ])
        cat_pipeline.fit(cX_train, cy_train)

        cproba = cat_pipeline.predict_proba(cX_test)
        cclasses = cat_pipeline.named_steps["clf"].classes_
        cpred = cclasses[np.argmax(cproba, axis=1)]
        ctop1 = accuracy_score(cy_test, cpred)
        ctop3 = top_k_accuracy_score(cy_test, cproba, k=3, labels=cclasses)
        print(f"  top-1 {ctop1:.3f} | top-3 {ctop3:.3f}   "
              f"(vs {top1:.3f} top-1 for the 60-class section model)")

        for calibrated in getattr(cat_pipeline.named_steps["clf"],
                                  "calibrated_classifiers_", []):
            estimator = getattr(calibrated, "estimator", None)
            if estimator is not None and hasattr(estimator, "coef_"):
                estimator.coef_ = estimator.coef_.astype("float32")
                estimator.intercept_ = estimator.intercept_.astype("float32")

        joblib.dump({"pipeline": cat_pipeline, "categories": sorted(set(cy_train))},
                    os.path.join(ART, "category_clf.joblib"), compress=3)
        cat_metrics = {
            "trained": True,
            "n_rows_used": int(len(cat_rows)),
            "n_categories": int(cat_rows["category"].nunique()),
            "top1_accuracy": round(float(ctop1), 4),
            "top3_accuracy": round(float(ctop3), 4),
            "section_model_top1_for_comparison": round(float(top1), 4),
            "note": "Predicts the offence category, not the exact section. The element "
                    "layer selects the section within a category at runtime, so this is "
                    "the part of the prediction the system actually consumes.",
        }
    else:
        print("  skipped: too few mapped rows")

    metrics["category_model"] = cat_metrics
    with open(os.path.join(ART, "metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=2)

    # ---------------------------------------------------------- retrieval index
    print("Building statute retrieval index ...")
    with open(os.path.join(DATA, "legal_kb.json"), encoding="utf-8") as fh:
        kb = json.load(fh)

    # Statute text is written in 1860 legal register; a complaint is not. Fold the
    # rule base's everyday trigger phrases for each provision into its document so
    # "my phone was stolen from my pocket" actually retrieves the theft section.
    with open(os.path.join(DATA, "crime_rules.json"), encoding="utf-8") as fh:
        rules = json.load(fh)
    everyday = {}
    for category in rules["categories"]:
        vocabulary = " . ".join(category.get("strong", []) + category.get("weak", [])
                                + [category["label"]])
        for provision in category["provisions"]:
            everyday.setdefault(provision["code"], []).append(vocabulary)

    codes, docs = [], []
    for bucket in ("ipc", "extra"):
        for entry in kb[bucket].values():
            title = entry["offence_name"]
            doc = " . ".join([title, title, title,
                              entry["description"],
                              " ".join(entry.get("keywords", [])),
                              " . ".join(everyday.get(entry["code"], []))])
            codes.append(entry["code"])
            docs.append(doc.lower())

    vec = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=1,
                          strip_accents="unicode", stop_words="english")
    matrix = vec.fit_transform(docs)
    joblib.dump({"vectorizer": vec, "matrix": matrix, "codes": codes},
                os.path.join(ART, "retrieval_index.joblib"), compress=3)
    print(f"  indexed {len(codes)} provisions")

    print(f"\nArtifacts written to {ART} in {time.time()-t0:.0f}s")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()