#!/usr/bin/env python3
import os
import glob
import logging
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep

import torch
from qdrant_client import QdrantClient
from qdrant_client import models as qdrant_models
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# =========================
# Config (env-overridable)
# =========================
DATA_DIR = os.environ.get("DATA_DIR", "/data")
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "uspto_patents")

# Vectorization controls
CONCURRENT_FILE_READERS = int(os.environ.get("CONCURRENT_FILE_READERS", "24"))
GPU_BATCH_SIZE = int(os.environ.get("GPU_BATCH_SIZE", "512"))
QDRANT_UPSERT_CHUNK = int(os.environ.get("QDRANT_UPSERT_CHUNK", "1000"))
MODEL_NAME = os.environ.get("MODEL_NAME", "all-MiniLM-L6-v2")

# Optional limiter during initial prod runs (0 = no limit)
LIMIT_FILES = int(os.environ.get("LIMIT_FILES", "0"))

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# =========================
# XML helpers
# =========================
def get_full_text_from_tag(element, tag_path):
    node = element.find(tag_path)
    if node is None:
        return ""
    return " ".join(t.strip() for t in node.itertext() if t and t.strip())


def parse_patent_xml(file_path):
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Fields
        title = get_full_text_from_tag(root, ".//invention-title")
        abstract_text = get_full_text_from_tag(root, ".//abstract")
        description_text = get_full_text_from_tag(root, ".//description")
        claims_text = get_full_text_from_tag(root, ".//claims")

        # Dates (try publication date, fall back to application date if available)
        pub_date_node = root.find(".//publication-reference/document-id/document-date")
        app_date_node = root.find(".//application-reference/document-id/date")
        filing_date = ""
        if pub_date_node is not None and pub_date_node.text:
            filing_date = pub_date_node.text
        elif app_date_node is not None and app_date_node.text:
            filing_date = app_date_node.text

        # Patent/publication number (publication doc-number is standard for A1/A9 etc.)
        doc_id_node = root.find(".//publication-reference/document-id/doc-number")
        patent_number = (doc_id_node.text or "").strip() if doc_id_node is not None else ""

        # Combined text for embedding
        combined_text = " ".join(filter(None, [title, abstract_text, description_text, claims_text]))
        if not combined_text:
            return None

        # Deterministic ID (prefer patent_number; else file basename)
        source_id_string = patent_number if patent_number else os.path.basename(file_path)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, source_id_string))

        # Preview + external URLs
        preview_source = abstract_text or description_text or title
        preview = (preview_source[:500] + "…") if len(preview_source) > 500 else preview_source

        google_url = f"https://patents.google.com/patent/US{patent_number}/en" if patent_number else ""

        return {
            "id": point_id,
            "text_for_embedding": combined_text,
            "payload": {
                "title": title,
                "abstract": abstract_text,
                "filingDate": filing_date,
                "patentNumber": patent_number,
                "googlePatentUrl": google_url,
                "preview": preview,
                "file_path": os.path.basename(file_path),
            },
        }
    except ET.ParseError:
        logging.error(f"Could not parse XML file: {file_path}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error parsing {file_path}: {e}")
        return None


def upsert_with_retry(client, collection_name, points, max_retries=3):
    for attempt in range(max_retries):
        try:
            client.upsert(collection_name=collection_name, points=points)
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                logging.error(f"Failed to upsert after {max_retries} attempts: {e}")
                raise
            wait_time = 2 ** attempt
            logging.warning(f"Upsert failed (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait_time}s...")
            sleep(wait_time)
    return False


def walk_xml_files(root_dir):
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            if f.lower().endswith(".xml"):
                yield os.path.join(dirpath, f)

def main():
    # ====== Model setup (multi-GPU) ======
    num_gpus = torch.cuda.device_count()
    logging.info(f"Loading SentenceTransformer: {MODEL_NAME}")

    if num_gpus > 1:
        logging.info(f"🔥 Loading model on {num_gpus} GPUs")
        models = [SentenceTransformer(MODEL_NAME, device=f"cuda:{i}") for i in range(num_gpus)]
        for m in models:
            m.eval()
        logging.info(f"✅ {num_gpus} models ready")
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        models = [SentenceTransformer(MODEL_NAME, device=device)]
        models[0].eval()
        logging.info(f"✅ Model ready on {models[0]._target_device}")

    # ====== Qdrant client ======
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=180)
    embedding_size = models[0].get_sentence_embedding_dimension()

    # Create or resume
    try:
        exists = client.collection_exists(COLLECTION_NAME)
    except Exception:
        try:
            client.get_collection(COLLECTION_NAME)
            exists = True
        except Exception:
            exists = False

    if not exists:
        logging.info(f"🆕 Creating collection '{COLLECTION_NAME}'")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qdrant_models.VectorParams(
                size=embedding_size,
                distance=qdrant_models.Distance.COSINE,
                on_disk=True,
            ),
        )
    else:
        logging.info(f"↩️  Resuming with existing collection '{COLLECTION_NAME}'")

    # ====== Resume-safety: fetch existing IDs ======
    logging.info("🔎 Scanning existing IDs in collection to enable resume…")
    existing_ids = set()
    scroll = client.scroll(collection_name=COLLECTION_NAME, limit=1000, with_payload=False)
    while True:
        if getattr(scroll, "points", None):
            existing_ids.update([p.id for p in scroll.points])
        if not getattr(scroll, "next_page_offset", None):
            break
        scroll = client.scroll(collection_name=COLLECTION_NAME, limit=1000, with_payload=False, offset=scroll.next_page_offset)
    logging.info(f"📦 Found {len(existing_ids):,} existing vectors")

    # ====== Stream XML files instead of list() ======
    xml_generator = walk_xml_files(DATA_DIR)
    if LIMIT_FILES and LIMIT_FILES > 0:
        from itertools import islice
        xml_generator = islice(xml_generator, LIMIT_FILES)

    from itertools import islice
    total_processed = 0
    BATCH_XML_COUNT = 1000  # process 1000 at a time

    while True:
        batch_files = list(islice(xml_generator, BATCH_XML_COUNT))
        if not batch_files:
            break

        parsed_docs = []
        with ThreadPoolExecutor(max_workers=CONCURRENT_FILE_READERS) as executor:
            futures = {executor.submit(parse_patent_xml, f): f for f in batch_files}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Parsing XML batch"):
                doc = future.result()
                if doc and doc["id"] not in existing_ids:
                    parsed_docs.append(doc)

        if not parsed_docs:
            continue

        texts = [d["text_for_embedding"] for d in parsed_docs]

        # Multi-GPU encoding
        if len(models) > 1:
            import numpy as np
            from threading import Thread
            chunk_size = max(1, len(texts) // len(models))
            embeddings_list = [None] * len(models)

            def encode_on_gpu(gpu_id, model, texts_chunk):
                emb = model.encode(
                    texts_chunk,
                    batch_size=GPU_BATCH_SIZE,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
                embeddings_list[gpu_id] = emb

            threads = []
            for i, model in enumerate(models):
                start = i * chunk_size
                end = len(texts) if i == (len(models) - 1) else start + chunk_size
                t = Thread(target=encode_on_gpu, args=(i, model, texts[start:end]))
                t.start()
                threads.append(t)
            for t in threads:
                t.join()

            import numpy as np
            embeddings = np.vstack([e for e in embeddings_list if e is not None])
        else:
            embeddings = models[0].encode(
                texts,
                batch_size=GPU_BATCH_SIZE,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )

        # ====== Upsert ======
        upsert_with_retry(
            client=client,
            collection_name=COLLECTION_NAME,
            points=qdrant_models.Batch(
                ids=[d["id"] for d in parsed_docs],
                vectors=embeddings.tolist(),
                payloads=[d["payload"] for d in parsed_docs],
            ),
        )

        total_processed += len(parsed_docs)
        logging.info(f"✅ Indexed {total_processed:,} so far…")

        # Manual cleanup
        del parsed_docs, texts, embeddings
        torch.cuda.empty_cache()

    logging.info(f"🎉 Done! Total indexed: {total_processed:,} into '{COLLECTION_NAME}'.")

if __name__ == "__main__":
    main()
