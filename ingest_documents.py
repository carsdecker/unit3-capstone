# ingest_documents.py — loads the 4 sample PDFs from S3 into OpenSearch.
# Based on the course lab (ingestion_pipeline_solution.py): Textract -> chunk -> embed -> index.
# Changes from the lab:
#   1. Embeddings via onnx_embed: the SAME code the deployed retrieval agent uses for questions,
#      so stored vectors and query vectors are guaranteed to match.
#   2. space_type "innerproduct", not "cosinesimil": faiss hnsw does not support cosinesimil
#      (Deployment Patterns README). onnx_embed's vectors are length 1, so the ranking is identical.
#   3. Endpoint from .env and our bucket name instead of placeholders.
# Safe to re-run: the index is only created if missing, and chunk IDs are fixed
# ("<file>-<n>"), so re-running overwrites chunks instead of duplicating them.
import os
import time
import boto3
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from onnx_embed import get_embedding

load_dotenv()

REGION = "us-east-1"
INDEX_NAME = "documents"
BUCKET = "doc-ingest-pipeline-cd"
DOCUMENTS = [
    "remote-work-policy.pdf",
    "retail-supply-chain-case-study.pdf",
    "q2-2026-client-report.pdf",
    "cloud-migration-playbook.pdf",
]


def get_opensearch_client():
    # Every request is signed with your AWS credentials; OpenSearch checks the
    # signature against the access policy from infra/opensearch-access-policy.json.
    credentials = boto3.Session().get_credentials()
    auth = AWS4Auth(credentials.access_key, credentials.secret_key,
                    REGION, "es", session_token=credentials.token)
    return OpenSearch(
        hosts=[{"host": os.environ["OPENSEARCH_ENDPOINT"], "port": 443}],
        http_auth=auth, use_ssl=True, verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def create_index(client):
    index_body = {
        "settings": {"index.knn": True},
        "mappings": {
            "properties": {
                "content": {"type": "text"},
                "source": {"type": "keyword"},
                "chunk_number": {"type": "integer"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 384,
                    "method": {"name": "hnsw", "space_type": "innerproduct", "engine": "faiss"},
                },
            }
        },
    }
    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=index_body)
        print(f"Created index '{INDEX_NAME}'")
    else:
        print(f"Index '{INDEX_NAME}' already exists")


def extract_text_from_s3_pdf(bucket: str, document_key: str) -> str:
    # Textract's async API: required for multi-page PDFs (the sync API only handles one page).
    textract = boto3.client("textract", region_name=REGION)
    job_id = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": document_key}}
    )["JobId"]

    for _ in range(60):  # poll for up to ~2 minutes
        response = textract.get_document_text_detection(JobId=job_id)
        status = response["JobStatus"]
        if status in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"Textract job for {document_key} did not finish in time")

    if status == "FAILED":
        raise RuntimeError(f"Textract failed for {document_key}: {response.get('StatusMessage')}")

    # Results can span several response pages; follow NextToken to collect every line.
    lines = [b["Text"] for b in response["Blocks"] if b["BlockType"] == "LINE"]
    next_token = response.get("NextToken")
    while next_token:
        response = textract.get_document_text_detection(JobId=job_id, NextToken=next_token)
        lines.extend(b["Text"] for b in response["Blocks"] if b["BlockType"] == "LINE")
        next_token = response.get("NextToken")
    return "\n".join(lines)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    # Course setting: 500-word chunks with 50 words shared between neighbours.
    words = text.split()
    return [" ".join(words[i:i + chunk_size])
            for i in range(0, len(words), chunk_size - overlap)]


def index_document(client, document_key: str, chunks: list[str]):
    for i, chunk in enumerate(chunks):
        client.index(
            index=INDEX_NAME,
            id=f"{document_key}-{i}",
            body={
                "content": chunk,
                "embedding": get_embedding(chunk),
                "source": document_key,
                "chunk_number": i,
            },
        )


if __name__ == "__main__":
    client = get_opensearch_client()
    create_index(client)

    for key in DOCUMENTS:
        text = extract_text_from_s3_pdf(BUCKET, key)
        chunks = chunk_text(text)
        index_document(client, key, chunks)
        print(f"{key}: {len(text.split())} words -> {len(chunks)} chunks")

    # OpenSearch makes new documents searchable about once a second; refresh now
    # so the count below includes everything we just added.
    client.indices.refresh(index=INDEX_NAME)
    print("Total chunks in index:", client.count(index=INDEX_NAME)["count"])