"""
MATLAB file utilities with S3 support.

Provides a drop-in replacement for scipy.io.loadmat that can handle S3 URIs.
"""

import io
from typing import Any, Dict, Optional, Union

import boto3
from botocore.exceptions import ClientError
from scipy.io import loadmat as scipy_loadmat


def loadmat(
    file_name: Union[str, io.IOBase],
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Load a MATLAB .mat file, supporting both local paths and S3 URIs.
    
    This is a drop-in replacement for scipy.io.loadmat that adds S3 support.
    For S3 URIs, the file is downloaded to a BytesIO buffer and then passed
    to scipy.io.loadmat.
    
    Parameters
    ----------
    file_name : str or file-like object
        The MATLAB file to load. Can be:
        - A local filesystem path (passed directly to scipy.io.loadmat)
        - An S3 URI (e.g., 's3://bucket/path/file.mat')
        - An already-open file-like object (passed directly)
    **kwargs : dict
        Additional keyword arguments passed to scipy.io.loadmat
        
    Returns
    -------
    dict
        Dictionary with variable names as keys and loaded arrays as values.
        
    Raises
    ------
    FileNotFoundError
        If the file cannot be found (local or S3)
    ValueError
        If the S3 URI is malformed
    RuntimeError
        If AWS credentials are not configured for S3 access
        
    Notes
    -----
    For S3 URIs, this function requires:
    - boto3 to be installed
    - AWS credentials to be configured (via environment variables,
      ~/.aws/credentials, or IAM roles)
    - The S3 bucket to be accessible
    
    The function preserves all scipy.io.loadmat functionality for local files.
    
    Examples
    --------
    >>> # Local file
    >>> data = loadmat('/path/to/file.mat')
    >>> 
    >>> # S3 file
    >>> data = loadmat('s3://my-bucket/path/file.mat')
    """
    # If it's already a file-like object, pass it through
    if hasattr(file_name, 'read'):
        return scipy_loadmat(file_name, **kwargs)
    
    # If it's not a string, try to pass it through
    if not isinstance(file_name, str):
        return scipy_loadmat(file_name, **kwargs)
    
    # Check if it's an S3 URI
    if file_name.startswith('s3://'):
        return _loadmat_from_s3(file_name, **kwargs)
    
    # Local file - pass directly to scipy
    return scipy_loadmat(file_name, **kwargs)


def _loadmat_from_s3(
    s3_uri: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Load a MATLAB file from S3.
    
    Downloads the file to a BytesIO buffer and passes it to scipy.io.loadmat.
    """
    import os
    from urllib.parse import urlparse
    
    # Parse S3 URI
    parsed = urlparse(s3_uri)
    
    if not parsed.netloc:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    if not key:
        raise ValueError(f"Invalid S3 URI (empty key): {s3_uri}")
    
    # Get AWS configuration from environment
    # These are the same variables used by ROS3 VFD
    aws_endpoint_url = os.environ.get('AWS_ENDPOINT_URL')
    aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    aws_default_region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
    
    # Check if we have credentials
    if not aws_access_key_id or not aws_secret_access_key:
        raise RuntimeError(
            "AWS credentials not configured. Please set AWS_ACCESS_KEY_ID "
            "and AWS_SECRET_ACCESS_KEY environment variables."
        )
    
    # Create S3 client with custom endpoint support
    s3_kwargs = {
        'endpoint_url': aws_endpoint_url,
        'region_name': aws_default_region,
    }
    
    # Filter out None values
    s3_kwargs = {k: v for k, v in s3_kwargs.items() if v is not None}
    
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            **s3_kwargs,
        )
        
        # Download file to BytesIO
        response = s3_client.get_object(Bucket=bucket, Key=key)
        file_buffer = io.BytesIO(response['Body'].read())
        
        # Pass buffer to scipy.loadmat
        return scipy_loadmat(file_buffer, **kwargs)
        
    except ClientError as e:
        error_msg = f"Failed to download {s3_uri} from S3: {e}"
        if e.response['Error']['Code'] == 'NoSuchKey':
            raise FileNotFoundError(error_msg)
        elif e.response['Error']['Code'] == 'NoSuchBucket':
            raise FileNotFoundError(error_msg)
        else:
            raise RuntimeError(error_msg)
    except Exception as e:
        raise RuntimeError(f"Error loading {s3_uri}: {e}")
