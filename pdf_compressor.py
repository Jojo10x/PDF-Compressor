import os
import sys
import logging
from pathlib import Path
from datetime import datetime
import tempfile
import shutil
import io
import hashlib
from collections import defaultdict

try:
    import fitz 
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except ImportError:
    PIKEPDF_AVAILABLE = False

try:
    from pypdf import PdfWriter, PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

INPUT_DIR = "input_pdfs"
OUTPUT_DIR = "output_pdfs" 
LOG_DIR = "logs"
COMPRESSION_LEVEL = "recommended"

COMPRESSION_SETTINGS = {
    "high": {
        "remove_blank_pages": True,
        "remove_duplicate_pages": True,
        "compress_images": True,
        "image_dpi": 150,
        "jpeg_quality": 60,
        "remove_metadata": True,
        "flatten_forms": True
    },
    "recommended": {
        "remove_blank_pages": True,
        "remove_duplicate_pages": True,
        "compress_images": True,
        "image_dpi": 200,
        "jpeg_quality": 75,
        "remove_metadata": False,
        "flatten_forms": False
    },
    "low": {
        "remove_blank_pages": False,
        "remove_duplicate_pages": False,
        "compress_images": True,
        "image_dpi": 300,
        "jpeg_quality": 90,
        "remove_metadata": False,
        "flatten_forms": False
    }
}

class PDFCompressor:
    def __init__(self):
        self.setup_directories()
        self.setup_logging()
        self.compression_stats = {
            'files_processed': 0,
            'total_original_size': 0,
            'total_compressed_size': 0,
            'errors': 0,
            'blank_pages_removed': 0,
            'duplicate_pages_removed': 0,
            'images_optimized': 0
        }
        self.settings = COMPRESSION_SETTINGS[COMPRESSION_LEVEL]

    def setup_directories(self):
        """Create necessary directories if they don't exist"""
        for directory in [INPUT_DIR, OUTPUT_DIR, LOG_DIR]:
            Path(directory).mkdir(exist_ok=True)
            
        readme_path = Path(INPUT_DIR) / "README.txt"
        if not readme_path.exists():
            with open(readme_path, 'w') as f:
                f.write("Place your PDF files here to be compressed.\n")
                f.write("The compressor will:\n")
                f.write("- Remove blank pages\n")
                f.write("- Remove duplicate pages\n")
                f.write("- Optimize images\n")
                f.write("- Compress content streams\n")
                f.write("Compressed files will be saved to 'output_pdfs' directory.\n")

    def setup_logging(self):
        """Setup logging configuration"""
        log_filename = datetime.now().strftime("pdf_compression_%Y%m%d_%H%M%S.log")
        log_path = Path(LOG_DIR) / log_filename
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_path),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Advanced PDF Content Compressor initialized")
        self.logger.info(f"Input directory: {INPUT_DIR}")
        self.logger.info(f"Output directory: {OUTPUT_DIR}")
        
        libs_available = []
        if PYMUPDF_AVAILABLE:
            libs_available.append("PyMuPDF")
        if PIL_AVAILABLE:
            libs_available.append("Pillow")
        if PIKEPDF_AVAILABLE:
            libs_available.append("pikepdf")
        if PYPDF_AVAILABLE:
            libs_available.append("pypdf")
        
        self.logger.info(f"Available libraries: {', '.join(libs_available)}")
        
        if not (PYMUPDF_AVAILABLE or PIKEPDF_AVAILABLE or PYPDF_AVAILABLE):
            self.logger.error("No PDF libraries available!")
            self.logger.info("Install with: pip install PyMuPDF pikepdf pypdf Pillow")
            sys.exit(1)

    def get_file_size(self, filepath):
        """Get file size in bytes"""
        return os.path.getsize(filepath)

    def format_size(self, size_bytes):
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

    def is_page_blank(self, page):
        """Check if a page is essentially blank using text and drawing content"""
        try:
            text_content = page.get_text().strip()
            
            if len(text_content) > 10: 
                return False
            
            drawings = page.get_drawings()
            if len(drawings) > 2: 
                return False
            
            images = page.get_images()
            if len(images) > 0:
                return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Error checking if page is blank: {e}")
            return False

    def get_page_content_hash(self, page):
        """Generate a hash of page content to detect duplicates"""
        try:
            text_content = page.get_text()
            images = page.get_images()
            drawings = page.get_drawings()
            
            content_parts = [
                text_content.strip(),
                str(len(images)),
                str(len(drawings))
            ]
            
            for img in images[:5]: 
                content_parts.append(str(img[1:4]))  
            
            content_string = "|".join(content_parts)
            return hashlib.md5(content_string.encode()).hexdigest()
            
        except Exception as e:
            self.logger.warning(f"Error generating page hash: {e}")
            return None

    def optimize_image_in_pdf(self, doc, xref):
        """Optimize a single image in the PDF"""
        try:
            if not PIL_AVAILABLE:
                return False

            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            
            img = Image.open(io.BytesIO(image_bytes))
            original_size = len(image_bytes)
            
            if original_size < 10000: 
                return False
            
            max_dimension = self.settings["image_dpi"] * 8.5 
            if img.width > max_dimension or img.height > max_dimension:
                ratio = min(max_dimension / img.width, max_dimension / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                self.logger.debug(f"Resized image to {new_size}")
            
            output = io.BytesIO()
            
            if image_ext.lower() in ['jpg', 'jpeg'] or img.mode == 'RGB':
                if img.mode in ('RGBA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'RGBA':
                        rgb_img.paste(img, mask=img.split()[-1])
                    else:
                        rgb_img.paste(img)
                    img = rgb_img
                
                img.save(output, format='JPEG', 
                        quality=self.settings["jpeg_quality"],
                        optimize=True)
            else:
                img.save(output, format='PNG', optimize=True)
            
            optimized_bytes = output.getvalue()
            
            if len(optimized_bytes) < original_size:
                doc.update_stream(xref, optimized_bytes)
                compression_ratio = (1 - len(optimized_bytes) / original_size) * 100
                self.logger.debug(f"Optimized image: {compression_ratio:.1f}% reduction")
                return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Failed to optimize image: {e}")
            return False

    def compress_with_pymupdf_advanced(self, input_path, output_path):
        """Advanced compression using PyMuPDF with content optimization"""
        try:
            doc = fitz.open(input_path)
            pages_to_keep = []
            page_hashes = set()
            images_optimized = 0
            blank_pages_removed = 0
            duplicate_pages_removed = 0
            
            self.logger.info(f"Analyzing {len(doc)} pages for optimization...")
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                if self.settings["remove_blank_pages"] and self.is_page_blank(page):
                    self.logger.debug(f"Page {page_num + 1} is blank - will remove")
                    blank_pages_removed += 1
                    continue
                
                if self.settings["remove_duplicate_pages"]:
                    page_hash = self.get_page_content_hash(page)
                    if page_hash and page_hash in page_hashes:
                        self.logger.debug(f"Page {page_num + 1} is duplicate - will remove")
                        duplicate_pages_removed += 1
                        continue
                    if page_hash:
                        page_hashes.add(page_hash)
                
                pages_to_keep.append(page_num)
            
            self.logger.info(f"Keeping {len(pages_to_keep)} pages (removed {blank_pages_removed} blank, {duplicate_pages_removed} duplicate)")
            
            new_doc = fitz.open()
            for page_num in pages_to_keep:
                new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            
            doc.close()
            doc = new_doc
            
            if self.settings["compress_images"] and PIL_AVAILABLE:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    images = page.get_images()
                    
                    for img in images:
                        xref = img[0]
                        if self.optimize_image_in_pdf(doc, xref):
                            images_optimized += 1
            
            if self.settings.get("remove_metadata", False):
                metadata = doc.metadata
                for key in list(metadata.keys()):
                    metadata[key] = ""
                doc.set_metadata(metadata)
            
            doc.save(output_path, 
                    garbage=4,     
                    deflate=True,   
                    clean=True)    
            
            doc.close()
            
            self.compression_stats['blank_pages_removed'] += blank_pages_removed
            self.compression_stats['duplicate_pages_removed'] += duplicate_pages_removed
            self.compression_stats['images_optimized'] += images_optimized
            
            self.logger.info(f"PyMuPDF optimization complete:")
            self.logger.info(f"  - Blank pages removed: {blank_pages_removed}")
            self.logger.info(f"  - Duplicate pages removed: {duplicate_pages_removed}")
            self.logger.info(f"  - Images optimized: {images_optimized}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"PyMuPDF advanced compression failed: {e}")
            return False

    def compress_with_pikepdf_enhanced(self, input_path, output_path):
        """Enhanced compression using pikepdf"""
        try:
            with pikepdf.open(input_path) as pdf:
                pdf.save(output_path, 
                        compress_streams=True,
                        recompress_flate=True,
                        object_stream_mode=pikepdf.ObjectStreamMode.generate,
                        normalize_content=True,
                        fix_metadata_version=True,
                        sanitize=True)
                return True
        except Exception as e:
            self.logger.error(f"pikepdf enhanced compression failed: {e}")
            return False

    def compress_with_pypdf_optimized(self, input_path, output_path):
        """Optimized compression using pypdf with content stream compression"""
        try:
            reader = PdfReader(input_path)
            writer = PdfWriter()
            
            pages_added = 0
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                
                try:
                    if hasattr(page, 'compress_content_streams'):
                        page.compress_content_streams()
                except:
                    pass
                
                writer.add_page(page)
                pages_added += 1
            
            try:
                if hasattr(writer, 'compress_identical_objects'):
                    writer.compress_identical_objects()
                if hasattr(writer, 'remove_duplicates'):
                    writer.remove_duplicates()
                if hasattr(writer, 'remove_images') and self.settings.get("remove_metadata"):
                    pass
            except:
                pass
            
            with open(output_path, 'wb') as output_file:
                writer.write(output_file)
            
            self.logger.info(f"pypdf processed {pages_added} pages")
            return True
            
        except Exception as e:
            self.logger.error(f"pypdf optimized compression failed: {e}")
            return False

    def compress_pdf(self, input_path, output_path):
        """Compress a single PDF file with advanced content optimization"""
        original_size = self.get_file_size(input_path)
        
        methods_to_try = []
        
        if PYMUPDF_AVAILABLE:
            methods_to_try.append(("PyMuPDF Advanced", self.compress_with_pymupdf_advanced))
        
        if PIKEPDF_AVAILABLE:
            methods_to_try.append(("pikepdf Enhanced", self.compress_with_pikepdf_enhanced))
        
        if PYPDF_AVAILABLE:
            methods_to_try.append(("pypdf Optimized", self.compress_with_pypdf_optimized))
        
        success = False
        method_used = "none"
        
        for method_name, method_func in methods_to_try:
            try:
                self.logger.info(f"Attempting compression with {method_name}...")
                success = method_func(input_path, output_path)
                if success and os.path.exists(output_path):
                    method_used = method_name
                    break
            except Exception as e:
                self.logger.warning(f"{method_name} failed: {e}")
                continue
        
        if not success or not os.path.exists(output_path):
            return False, original_size, 0, "none"
        
        compressed_size = self.get_file_size(output_path)
        
        if compressed_size >= original_size:
            os.remove(output_path)
            shutil.copy2(input_path, output_path)
            compressed_size = original_size
            self.logger.warning(f"Compressed file was larger - kept original size")
        
        return True, original_size, compressed_size, method_used

    def find_pdf_files(self):
        """Find all PDF files in the input directory"""
        input_path = Path(INPUT_DIR)
        pdf_files = []
        
        for file_path in input_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() == '.pdf':
                if file_path.name != "README.txt":
                    pdf_files.append(file_path)
        
        return pdf_files

    def run_compression(self):
        """Main compression process"""
        self.logger.info("Starting advanced PDF compression process...")
        self.logger.info(f"Compression level: {COMPRESSION_LEVEL}")
        self.logger.info(f"Settings: {self.settings}")
        
        pdf_files = self.find_pdf_files()
        
        if not pdf_files:
            self.logger.info("No PDF files found in input directory")
            return
        
        self.logger.info(f"Found {len(pdf_files)} PDF files to compress")
        
        for pdf_file in pdf_files:
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Processing: {pdf_file.name}")
            
            output_filename = f"compressed_{pdf_file.stem}.pdf"
            output_path = Path(OUTPUT_DIR) / output_filename
            
            try:
                success, original_size, compressed_size, method = self.compress_pdf(
                    str(pdf_file), str(output_path)
                )
                
                if success:
                    if original_size > 0:
                        compression_ratio = ((original_size - compressed_size) / original_size) * 100
                    else:
                        compression_ratio = 0
                    
                    self.logger.info(f"✓ Compression successful using {method}")
                    self.logger.info(f"  Original size: {self.format_size(original_size)}")
                    self.logger.info(f"  Compressed size: {self.format_size(compressed_size)}")
                    self.logger.info(f"  Space saved: {compression_ratio:.1f}%")
                    self.logger.info(f"  Output: {output_filename}")
                    
                    self.compression_stats['files_processed'] += 1
                    self.compression_stats['total_original_size'] += original_size
                    self.compression_stats['total_compressed_size'] += compressed_size
                    
                else:
                    self.logger.error(f"✗ Failed to compress {pdf_file.name}")
                    self.compression_stats['errors'] += 1
                    
            except Exception as e:
                self.logger.error(f"✗ Error processing {pdf_file.name}: {e}")
                self.compression_stats['errors'] += 1

    def print_summary(self):
        """Print compression summary"""
        stats = self.compression_stats
        
        self.logger.info(f"\n{'='*60}")
        self.logger.info("ADVANCED COMPRESSION SUMMARY")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Files processed: {stats['files_processed']}")
        self.logger.info(f"Blank pages removed: {stats['blank_pages_removed']}")
        self.logger.info(f"Duplicate pages removed: {stats['duplicate_pages_removed']}")
        self.logger.info(f"Images optimized: {stats['images_optimized']}")
        self.logger.info(f"Errors: {stats['errors']}")
        
        if stats['files_processed'] > 0:
            total_saved = stats['total_original_size'] - stats['total_compressed_size']
            if stats['total_original_size'] > 0:
                overall_compression = (total_saved / stats['total_original_size']) * 100
            else:
                overall_compression = 0
            
            self.logger.info(f"Total original size: {self.format_size(stats['total_original_size'])}")
            self.logger.info(f"Total compressed size: {self.format_size(stats['total_compressed_size'])}")
            self.logger.info(f"Total space saved: {self.format_size(total_saved)} ({overall_compression:.1f}%)")
        
        self.logger.info(f"{'='*60}")

def main():
    """Main function"""
    print("Advanced PDF Compressor - Content Optimization")
    print("==============================================")
    print(f"Compression level: {COMPRESSION_LEVEL}")
    print(f"Features enabled: {list(COMPRESSION_SETTINGS[COMPRESSION_LEVEL].keys())}")
    print()
    
    compressor = PDFCompressor()
    
    compressor.run_compression()
    
    compressor.print_summary()
    
    print(f"\nCheck the '{OUTPUT_DIR}' directory for compressed files")
    print(f"Logs are saved in the '{LOG_DIR}' directory")

if __name__ == "__main__":
    main()