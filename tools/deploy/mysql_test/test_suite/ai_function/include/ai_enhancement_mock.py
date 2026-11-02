"""Deterministic local service for AI expression protocol and row mapping tests."""
import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def embedding(text, dimension):
    seed = hashlib.sha256(text.encode()).digest()
    return [round((seed[i % len(seed)] - 128) / 128, 6) for i in range(dimension)]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.endswith('/chat/completions'):
                answer = body['messages'][-1]['content']
                response = {'choices': [{'message': {'content': answer}}]}
            elif self.path.endswith('/api/generate'):
                assert body['stream'] is False
                response = {'response': body['prompt'], 'done': True}
            elif self.path.endswith('/embeddings') or self.path.endswith('/api/embed'):
                inputs = body['input']
                if isinstance(inputs, str):
                    inputs = [inputs]
                vectors = [embedding(s, body.get('dimensions', 768)) for s in inputs]
                if self.path.endswith('/api/embed'):
                    response = {'embeddings': vectors}
                else:
                    # Deliberately reverse results to verify index-based association.
                    response = {'data': list(reversed([
                        {'index': i, 'embedding': v} for i, v in enumerate(vectors)]))}
            elif self.path.endswith('/rerank'):
                query = set(body['query'].lower().split())
                results = []
                for i, doc in enumerate(body['documents']):
                    terms = set(doc.lower().split())
                    score = len(query & terms) / max(1, len(query | terms))
                    results.append({'index': i, 'relevance_score': score})
                response = {'results': list(reversed(results))}
            else:
                self.send_error(404)
                return
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (ValueError, KeyError, AssertionError, TypeError):
            self.send_error(400, 'Invalid AI request')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    ThreadingHTTPServer(('0.0.0.0', args.port), Handler).serve_forever()
