"""
Debug script to compare boto3 vs ROS3 VFD request patterns.
Spin up a mock S3 server, log all requests, and compare what's being sent.
"""
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import json
import datetime

import h5py
import boto3
from io import BytesIO


# Constants
SERVER_PORT = 8899
TEST_BUCKET = "test-bucket"
TEST_FILE = "sample_test.h5"
FAKE_AWS_ACCESS_KEY = "access-key"
FAKE_AWS_SECRET_KEY = "secret-key"

# Global request log
request_log = []


class MockS3Handler(BaseHTTPRequestHandler):
    """Simple mock S3 handler that logs all requests."""
    
    def log_message(self, format, *args):
        """Override to suppress default logging but log errors."""
        if format.startswith("code"):
            # This is the response code logging
            print(f"Response: {args}")
        # Otherwise suppress
        pass
    
    def _log_custom(self, method):
        """Custom request logging."""
        timestamp = datetime.datetime.now().isoformat()
        
        request_info = {
            "timestamp": timestamp,
            "method": method,
            "path": self.path,
            "headers": dict(self.headers),
            "client_address": self.client_address
        }
        
        request_log.append(request_info)
        
        # Print to console
        print(f"\n{'='*60}")
        print(f"[{timestamp}] {method} {self.path}")
        print(f"{'='*60}")
        print("Headers:")
        for key, value in self.headers.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}\n")
    
    def do_GET(self):
        """Handle GET requests."""
        self._log_custom("GET")
        # Return a minimal HDF5-like response
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        # Don't actually send file data for now
    
    def do_HEAD(self):
        """Handle HEAD requests."""
        self._log_custom("HEAD")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", "50938")
        self.send_header("ETag", "dummy-etag")
        self.end_headers()
    
    def do_PUT(self):
        """Handle PUT requests."""
        self._log_custom("PUT")
        self.send_response(200)
        self.end_headers()
    
    def do_POST(self):
        """Handle POST requests."""
        self._log_custom("POST")
        self.send_response(200)
        self.end_headers()
    
    def do_DELETE(self):
        """Handle DELETE requests."""
        self._log_custom("DELETE")
        self.send_response(204)
        self.end_headers()
    
    def do_OPTIONS(self):
        """Handle OPTIONS requests."""
        self._log_custom("OPTIONS")
        self.send_response(200)
        self.end_headers()
    
    def do_LISTBUCKETS(self):
        """Handle bucket listing."""
        self.log_request("LISTBUCKETS")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Owner>
        <ID>owner-id</ID>
        <DisplayName>owner-display-name</DisplayName>
    </Owner>
    <Buckets>
        <Bucket>
            <Name>{TEST_BUCKET}</Name>
            <CreationDate>2026-01-01T00:00:00Z</CreationDate>
        </Bucket>
    </Buckets>
</ListAllMyBucketsResult>"""
        self.send_header("Content-Length", str(len(xml_response)))
        self.end_headers()
        self.wfile.write(xml_response.encode())


def start_mock_server():
    """Start the mock S3 server in a background thread."""
    server = HTTPServer(("localhost", SERVER_PORT), MockS3Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"✅ Mock S3 server started on port {SERVER_PORT}")
    return server


def reset_request_log():
    """Clear the request log."""
    global request_log
    request_log = []


def test_boto3_request(endpoint):
    """Make a request using boto3 and log what it sends."""
    print("\n" + "="*60)
    print("TESTING BOTO3 REQUEST")
    print("="*60)
    
    reset_request_log()
    
    try:
        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=FAKE_AWS_ACCESS_KEY,
            aws_secret_access_key=FAKE_AWS_SECRET_KEY,
            region_name="us-east-1"
        )
        
        # Try to head the object
        print(f"\nAttempting HEAD request for s3://{TEST_BUCKET}/{TEST_FILE}...")
        s3_client.head_object(Bucket=TEST_BUCKET, Key=TEST_FILE)
        print("✅ boto3 HEAD request successful")
        
    except Exception as e:
        print(f"❌ boto3 request failed: {e}")
    
    return request_log.copy()


def test_ros3_vfd_request(endpoint, s3_uri):
    """Make a request using ROS3 VFD and log what it sends."""
    print("\n" + "="*60)
    print("TESTING ROS3 VFD REQUEST")
    print("="*60)
    
    reset_request_log()
    
    # Save old environment
    old_vars = {
        "HDF5_ROS3_VFD_DEBUG": os.environ.get("HDF5_ROS3_VFD_DEBUG"),
        "H5ROSS3_ENDPOINT": os.environ.get("H5ROSS3_ENDPOINT"),
        "H5ROSS3_NO_VERIFY_SSL": os.environ.get("H5ROSS3_NO_VERIFY_SSL"),
        "H5ROSS3_PATH_STYLE": os.environ.get("H5ROSS3_PATH_STYLE"),
        "H5ROSS3_AUTH_METHOD": os.environ.get("H5ROSS3_AUTH_METHOD"),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION"),
    }
    
    try:
        # Configure ROS3 environment
        clean_endpoint = endpoint.replace("http://", "").replace("https://", "")
        os.environ["HDF5_ROS3_VFD_DEBUG"] = "1"
        os.environ["H5ROSS3_ENDPOINT"] = clean_endpoint
        os.environ["H5ROSS3_NO_VERIFY_SSL"] = "1"
        os.environ["H5ROSS3_PATH_STYLE"] = "1"
        os.environ["H5ROSS3_AUTH_METHOD"] = "ENV_VAR"
        os.environ["AWS_ACCESS_KEY_ID"] = FAKE_AWS_ACCESS_KEY
        os.environ["AWS_SECRET_ACCESS_KEY"] = FAKE_AWS_SECRET_KEY
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        
        print(f"\nAttempting to open {s3_uri} with ROS3 VFD...")
        print(f"Using endpoint: {clean_endpoint}")
        
        try:
            with h5py.File(s3_uri, "r", driver="ros3") as f:
                print(f"✅ ROS3 VFD opened file successfully")
                print(f"   Datasets: {list(f.keys())}")
        except Exception as e:
            print(f"❌ ROS3 VFD failed: {e}")
        
    finally:
        # Restore old environment
        for var, old_value in old_vars.items():
            if old_value is not None:
                os.environ[var] = old_value
            elif var in os.environ:
                del os.environ[var]
    
    return request_log.copy()


def compare_requests(boto3_log, ros3_log):
    """Compare boto3 and ROS3 VFD requests."""
    print("\n" + "="*60)
    print("REQUEST COMPARISON")
    print("="*60)
    
    print(f"\n📊 boto3 made {len(boto3_log)} request(s)")
    for i, req in enumerate(boto3_log):
        print(f"\n  Request {i+1}:")
        print(f"    Method: {req['method']}")
        print(f"    Path: {req['path']}")
        print(f"    Authorization: {req['headers'].get('Authorization', 'NONE')}")
        print(f"    X-Amz-Date: {req['headers'].get('X-Amz-Date', 'NONE')}")
        print(f"    Host: {req['headers'].get('Host', 'NONE')}")
    
    print(f"\n📊 ROS3 VFD made {len(ros3_log)} request(s)")
    for i, req in enumerate(ros3_log):
        print(f"\n  Request {i+1}:")
        print(f"    Method: {req['method']}")
        print(f"    Path: {req['path']}")
        print(f"    Authorization: {req['headers'].get('Authorization', 'NONE')}")
        print(f"    X-Amz-Date: {req['headers'].get('X-Amz-Date', 'NONE')}")
        print(f"    Host: {req['headers'].get('Host', 'NONE')}")
    
    # Detailed comparison
    if boto3_log and ros3_log:
        print("\n" + "="*60)
        print("DETAILED DIFFERENCES")
        print("="*60)
        
        boto3_req = boto3_log[0]
        ros3_req = ros3_log[0]
        
        print("\n🔍 Header Comparison:")
        all_keys = set(boto3_req['headers'].keys()) | set(ros3_req['headers'].keys())
        for key in sorted(all_keys):
            boto_val = boto3_req['headers'].get(key, 'MISSING')
            ros3_val = ros3_req['headers'].get(key, 'MISSING')
            if boto_val != ros3_val:
                print(f"  {key}:")
                print(f"    boto3: {boto_val[:100]}{'...' if len(boto_val) > 100 else ''}")
                print(f"    ROS3:  {ros3_val[:100]}{'...' if len(ros3_val) > 100 else ''}")
                print()


def main():
    """Main diagnostic execution."""
    print("="*60)
    print("DEBUG: Comparing boto3 vs ROS3 VFD Request Patterns")
    print("="*60)
    
    endpoint = f"http://localhost:{SERVER_PORT}"
    s3_uri_simple = f"s3://{TEST_BUCKET}/{TEST_FILE}"
    s3_uri_full = f"s3://localhost:{SERVER_PORT}/{TEST_BUCKET}/{TEST_FILE}"
    
    # Start mock server
    server = start_mock_server()
    time.sleep(1)  # Give server time to start
    
    try:
        # Test boto3
        boto3_log = test_boto3_request(endpoint)
        
        # Small delay between tests
        time.sleep(1)
        
        # Reset for ROS3 test
        reset_request_log()
        
        # Test ROS3 VFD with simple URI
        print("\n" + "="*60)
        print("Testing ROS3 with SIMPLE URI: s3://bucket/key")
        print("="*60)
        ros3_simple_log = test_ros3_vfd_request(endpoint, s3_uri_simple)
        
        # Compare
        compare_requests(boto3_log, ros3_simple_log)
        
        # Reset for second ROS3 test
        reset_request_log()
        
        # Test ROS3 VFD with full URI
        print("\n" + "="*60)
        print("Testing ROS3 with FULL URI: s3://host:port/bucket/key")
        print("="*60)
        ros3_full_log = test_ros3_vfd_request(endpoint, s3_uri_full)
        
        # Compare
        compare_requests(boto3_log, ros3_full_log)
        
    finally:
        server.shutdown()
        print(f"\n✅ Mock server shutdown")


if __name__ == "__main__":
    main()
