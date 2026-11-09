"""
Spike test: Validate ROS3 VFD + VersityGW compatibility.
This must pass before proceeding to full implementation.
"""
import os
import sys
import time
import tempfile
import subprocess
from pathlib import Path

import h5py
import numpy as np
import boto3
from botocore.config import Config


# Constants
VERSITYGW_IMAGE = "versity/versitygw:latest"
CONTAINER_NAME = "ros3-spike-test-gateway"
S3_PORT = 7070  # VersityGW default HTTP port
TEST_BUCKET = "test-bucket"
TEST_FILE = "sample_test.h5"
DATA_DIR = "/data"  # Mount point in container for filesystem backend

# AWS credentials for VersityGW (accepts any values)
FAKE_AWS_ACCESS_KEY = "access-key"
FAKE_AWS_SECRET_KEY = "secret-key"


def check_ros3_capability():
    """Verify that h5py has ROS3 VFD support."""
    print("🔍 Checking ROS3 capability...")
    
    # Check h5py version and source
    print(f"   h5py version: {h5py.__version__}")
    print(f"   h5py location: {h5py.__file__}")
    
    # Check HDF5 library version
    try:
        lib_version = h5py.h5.get_libversion()
        print(f"   HDF5 library version: {'.'.join(map(str, lib_version))}")
    except Exception as e:
        print(f"   ⚠️  Could not get HDF5 version: {e}")
    
    print("   ℹ️  Assuming ROS3 capability (actual test happens in test_ros3_basic_read)")
    return True


def start_versitygw_server(data_dir: Path) -> str | None:
    """Start VersityGW in a Docker container with filesystem backend."""
    print("🚀 Starting VersityGW container...")
    
    # Map local data dir to container's /data
    cmd = [
        "docker", "run", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{S3_PORT}:{S3_PORT}",
        "-v", f"{data_dir}:{DATA_DIR}",
        VERSITYGW_IMAGE,
        "--port", f":{S3_PORT}",
        "--access", FAKE_AWS_ACCESS_KEY,
        "--secret", FAKE_AWS_SECRET_KEY,
        "posix",
        DATA_DIR
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()
        print(f"   ✅ Container started: {container_id}")
        
        # Wait for server to be ready
        import socket
        for i in range(60):  # Try for 60 seconds
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(('localhost', S3_PORT))
                sock.close()
                print(f"   ✅ Server is ready at port {S3_PORT}")
                return f"http://localhost:{S3_PORT}"
            except (socket.error, ConnectionRefusedError):
                if i % 10 == 0:
                    print(f"   ⏳ Waiting for server... ({i+1}/60)")
                time.sleep(1)
        
        print("   ❌ Server did not become ready in time")
        return None
        
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Failed to start container: {e.stderr}")
        return None


def stop_versitygw_server():
    """Stop and remove the VersityGW container."""
    print("🛑 Stopping VersityGW container...")
    
    # Stop container
    subprocess.run(["docker", "stop", CONTAINER_NAME], 
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Remove container
    subprocess.run(["docker", "rm", CONTAINER_NAME], 
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    print("   ✅ Container stopped and removed")


def create_bucket_and_upload(endpoint: str, hdf5_path: Path, data_dir: Path) -> str | None:
    """Create a bucket and upload the HDF5 file using boto3."""
    print("📤 Creating bucket and uploading file...")
    
    try:
        # Create S3 client pointing to VersityGW
        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=FAKE_AWS_ACCESS_KEY,
            aws_secret_access_key=FAKE_AWS_SECRET_KEY,
            region_name="us-east-1",
            config=Config(
                retries={"max_attempts": 3},
                signature_version="s3v4"
            )
        )
        
        # Create bucket
        try:
            s3_client.create_bucket(Bucket=TEST_BUCKET)
            print(f"   ✅ Bucket '{TEST_BUCKET}' created")
        except s3_client.exceptions.BucketAlreadyExists:
            print(f"   ⚠️  Bucket '{TEST_BUCKET}' already exists")
        except s3_client.exceptions.BucketAlreadyOwnedByYou:
            print(f"   ⚠️  Bucket '{TEST_BUCKET}' already owned by us")
        
        # Upload file
        s3_client.upload_file(str(hdf5_path), TEST_BUCKET, TEST_FILE)
        print(f"   ✅ File '{TEST_FILE}' uploaded")
        
        return f"s3://{TEST_BUCKET}/{TEST_FILE}"
        
    except Exception as e:
        print(f"   ❌ Upload failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_ros3_basic_read(endpoint: str, s3_uri: str, original_path: Path) -> bool:
    """Test basic HDF5 read via ROS3 VFD."""
    print("🔬 Testing ROS3 basic read...")
    
    # Save old environment variables
    old_vars = {
        "AWS_ENDPOINT_URL": os.environ.get("AWS_ENDPOINT_URL"),
        "H5ROSS3_ENDPOINT": os.environ.get("H5ROSS3_ENDPOINT"),
        "H5ROSS3_NO_VERIFY_SSL": os.environ.get("H5ROSS3_NO_VERIFY_SSL"),
        "H5ROSS3_PATH_STYLE": os.environ.get("H5ROSS3_PATH_STYLE"),
        "H5ROSS3_AUTH_METHOD": os.environ.get("H5ROSS3_AUTH_METHOD"),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION"),
    }
    
    try:
        # Configure ROS3 environment for VersityGW
        # Strip http:// or https:// from endpoint for H5ROSS3_ENDPOINT
        clean_endpoint = endpoint.replace("http://", "").replace("https://", "")
        
        print(f"   📋 Base Configuration:")
        print(f"      AWS_ENDPOINT_URL={endpoint}")
        print(f"      H5ROSS3_NO_VERIFY_SSL=1")
        print(f"      H5ROSS3_PATH_STYLE=1")
        print(f"      AWS_DEFAULT_REGION=us-east-1")
        
        # KEY FIX: Use AWS_ENDPOINT_URL instead of H5ROSS3_ENDPOINT
        os.environ["AWS_ENDPOINT_URL"] = endpoint
        os.environ["H5ROSS3_NO_VERIFY_SSL"] = "1"
        os.environ["H5ROSS3_PATH_STYLE"] = "1"
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        
        # Try different auth methods
        for auth_method in ["ENV_VAR", "ANONYMOUS"]:
            print(f"\n   🔐 Trying auth method: {auth_method}")
            os.environ["H5ROSS3_AUTH_METHOD"] = auth_method
            
            if auth_method == "ENV_VAR":
                print(f"      AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}")
                print(f"      AWS_SECRET_ACCESS_KEY={'*' * len(FAKE_AWS_SECRET_KEY)}")
                os.environ["AWS_ACCESS_KEY_ID"] = FAKE_AWS_ACCESS_KEY
                os.environ["AWS_SECRET_ACCESS_KEY"] = FAKE_AWS_SECRET_KEY
            else:
                print(f"      Using anonymous access")
                # Clear credentials for anonymous
                os.environ.pop("AWS_ACCESS_KEY_ID", None)
                os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
            
            try:
                # Try to open the file via ROS3
                with h5py.File(s3_uri, "r", driver="ros3") as f:
                    print(f"   📂 Datasets in file: {list(f.keys())}")
                    
                    # List and read datasets
                    datasets = list(f.keys())
                    
                    if datasets:
                        # Just verify we can access the first dataset
                        first_ds = f[datasets[0]]
                        arr = np.array(first_ds)
                        print(f"   ✅ Read '{datasets[0]}': shape={arr.shape}, dtype={arr.dtype}")
                        return True
                    else:
                        print(f"   ❌ No datasets found in file")
                        return False
            except Exception as e:
                print(f"   ❌ ROS3 read failed with {auth_method}: {e}")
                # Continue to try next auth method
                continue
        
        # If we get here, all auth methods failed
        print(f"   ❌ All auth methods exhausted")
        return False
                
    except Exception as e:
        print(f"   ❌ ROS3 read failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Restore old environment variables
        for var, old_value in old_vars.items():
            if old_value is not None:
                os.environ[var] = old_value
            elif var in os.environ:
                del os.environ[var]


def main():
    """Main spike test execution."""
    print("=" * 60)
    print("SPIKE TEST: ROS3 VFD + VersityGW Compatibility")
    print("=" * 60)
    
    endpoint = None
    s3_uri = None
    temp_base = None
    data_dir = None
    hdf5_path = None
    
    try:
        # Step 0: Check ROS3 capability
        if not check_ros3_capability():
            print("\n❌ ABORTING: ROS3 VFD not available in this h5py installation")
            print("   Solution: Use conda-forge h5py (>=3.10.0) and hdf5 (>=1.14.3)")
            return 1
        
        # Step 1: Create persistent data directory for VersityGW backend
        print("\n📁 Setting up backend storage...")
        temp_base = tempfile.mkdtemp(prefix="ros3_spike_")
        data_dir = Path(temp_base) / "backend"
        data_dir.mkdir(exist_ok=True)
        
        # Create temporary HDF5 file
        hdf5_path = data_dir / TEST_FILE
        
        # Copy existing sample file or create new one
        sample_source = Path("data/sample_test.h5")
        if sample_source.exists():
            import shutil
            shutil.copy(sample_source, hdf5_path)
            print(f"   ✅ Copied existing sample: {hdf5_path}")
        else:
            print(f"   ❌ Sample file not found: {sample_source}")
            print(f"   ℹ️  Run: python create_sample_hdf5.py --output data/sample_test.h5")
            return 1
        
        # Step 2: Start VersityGW server
        endpoint = start_versitygw_server(data_dir)
        if not endpoint:
            return 1
        
        # Give server extra time to stabilize
        time.sleep(3)
        
        # Step 3: Setup bucket and file in backend
        s3_uri = create_bucket_and_upload(endpoint, hdf5_path, data_dir)
        if not s3_uri:
            return 1
        
        print(f"   ℹ️  S3 URI: {s3_uri}")
        
        # Quick verification: Ensure boto3 can read the file back
        print("\n   🔄 Verifying boto3 can read the file...")
        try:
            s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=FAKE_AWS_ACCESS_KEY,
                aws_secret_access_key=FAKE_AWS_SECRET_KEY,
                region_name="us-east-1"
            )
            # Get object info
            obj_info = s3_client.head_object(Bucket=TEST_BUCKET, Key=TEST_FILE)
            print(f"   ✅ boto3 can access file: size={obj_info['ContentLength']} bytes")
        except Exception as e:
            print(f"   ❌ boto3 cannot read file: {e}")
            return 1
        
        # For ROS3 with custom endpoint, try different URI formats
        endpoint_host = endpoint.replace("http://", "").replace("https://", "")
        uris_to_try = [
            s3_uri,  # s3://bucket/key with H5ROSS3_ENDPOINT
            f"s3://{endpoint_host}/{TEST_BUCKET}/{TEST_FILE}",  # Endpoint in URI
        ]
        
        # Step 4: Test ROS3 read with each URI
        success = False
        for ros3_uri in uris_to_try:
            print(f"\n   🎯 Trying ROS3 URI: {ros3_uri}")
            if test_ros3_basic_read(endpoint, ros3_uri, hdf5_path):
                success = True
                break
        
        if success:
            print("\n✅ SPIKE TEST PASSED!")
            print("   ROS3 VFD + VersityGW combination works correctly.")
            print("   Safe to proceed with implementation.")
            return 0
        else:
            print("\n❌ SPIKE TEST FAILED!")
            print("   ROS3 VFD + VersityGW combination does not work.")
            print("   Check: h5py version, ROS3 support, container logs")
            return 1
            
    finally:
        # Cleanup
        if endpoint:
            stop_versitygw_server()
        if temp_base and Path(temp_base).exists():
            import shutil
            shutil.rmtree(temp_base)
            print(f"   ✅ Cleaned up temp directory: {temp_base}")


if __name__ == "__main__":
    sys.exit(main())
