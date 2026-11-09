"""
Script to create a sample HDF5 file for testing ROS3 VFD compatibility.
"""
import numpy as np
import h5py
import argparse
from pathlib import Path


def create_sample_hdf5(output_path: str) -> None:
    """Create a sample HDF5 file with test datasets."""
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    with h5py.File(output_path, "w") as f:
        # Small dataset
        f.create_dataset(
            "small_matrix",
            data=np.random.rand(10, 10).astype(np.float32),
            compression="gzip"
        )
        
        # Medium dataset
        f.create_dataset(
            "medium_matrix",
            data=np.random.rand(100, 100).astype(np.float32),
            compression="gzip"
        )
        
        # Vector dataset
        f.create_dataset(
            "vector",
            data=np.random.rand(1000).astype(np.float32),
            compression="gzip"
        )
    
    print(f"✅ Created sample HDF5 file: {output_path_obj.resolve()}")
    print(f"   Size: {output_path_obj.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create sample HDF5 file")
    parser.add_argument("--output", "-o", type=str, default="sample_test.h5",
                       help="Output HDF5 file path")
    args = parser.parse_args()
    create_sample_hdf5(args.output)
