"""
Excel Data Processor for RAGAnything using pandas

This module provides functionality to process Excel files using pandas
and integrate them into the RAGAnything pipeline for text-based analysis.
"""

import pandas as pd
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass

from lightrag.utils import logger


@dataclass
class ExcelProcessingConfig:
    """Configuration for Excel processing"""

    max_rows: Optional[int] = None  # Limit number of rows (None = all rows)
    sheet_name: Union[str, int, List[str]] = 0  # Sheet name(s) or index to process
    include_summary: bool = True  # Include dataset summary
    include_column_info: bool = True  # Include column information
    chunk_size: int = 100  # Number of rows per chunk for processing
    convert_to_text: bool = True  # Convert data to natural language text
    include_statistics: bool = True  # Include basic statistics


class ExcelDataProcessor:
    """Process Excel files using pandas and prepare them for RAGAnything"""

    def __init__(self, config: ExcelProcessingConfig = None):
        self.config = config or ExcelProcessingConfig()
        self.logger = logger

    def load_excel_data(self, file_path: str) -> pd.DataFrame:
        """Load Excel data using pandas"""
        try:
            self.logger.info(f"Loading Excel file: {file_path}")

            # Load the Excel file
            df = pd.read_excel(
                file_path, sheet_name=self.config.sheet_name, nrows=self.config.max_rows
            )

            # If multiple sheets were loaded, handle appropriately
            if isinstance(df, dict):
                # Multiple sheets - combine them or process separately
                combined_data = []
                for sheet_name, sheet_df in df.items():
                    sheet_df["_sheet_name"] = sheet_name  # Add sheet identifier
                    combined_data.append(sheet_df)
                df = pd.concat(combined_data, ignore_index=True)

            self.logger.info(
                f"Loaded Excel data: {df.shape[0]} rows, {df.shape[1]} columns"
            )
            return df

        except Exception as e:
            self.logger.error(f"Error loading Excel file {file_path}: {str(e)}")
            raise

    def generate_dataset_summary(self, df: pd.DataFrame) -> str:
        """Generate a natural language summary of the dataset"""
        summary_parts = []

        # Basic information
        summary_parts.append("Dataset Overview:")
        summary_parts.append(f"- Total rows: {len(df)}")
        summary_parts.append(f"- Total columns: {len(df.columns)}")

        # Column information
        if self.config.include_column_info:
            summary_parts.append("\nColumn Information:")
            for col in df.columns:
                col_type = str(df[col].dtype)
                non_null_count = df[col].count()
                null_count = len(df) - non_null_count

                summary_parts.append(
                    f"- {col}: {col_type} ({non_null_count} non-null, {null_count} null values)"
                )

                # Add sample values for categorical/text columns
                if df[col].dtype == "object":
                    unique_count = df[col].nunique()
                    if unique_count <= 10:
                        unique_values = df[col].unique()[:5]
                        summary_parts.append(
                            f"  Sample values: {', '.join(map(str, unique_values))}"
                        )
                    else:
                        summary_parts.append(f"  {unique_count} unique values")

        # Basic statistics for numerical columns
        if self.config.include_statistics:
            numeric_cols = df.select_dtypes(include=["number"]).columns
            if len(numeric_cols) > 0:
                summary_parts.append("\nNumerical Statistics:")
                for col in numeric_cols:
                    stats = df[col].describe()
                    summary_parts.append(
                        f"- {col}: mean={stats['mean']:.2f}, "
                        f"std={stats['std']:.2f}, "
                        f"min={stats['min']:.2f}, "
                        f"max={stats['max']:.2f}"
                    )

        return "\n".join(summary_parts)

    def convert_dataframe_to_text_chunks(self, df: pd.DataFrame) -> List[str]:
        """Convert DataFrame to text chunks suitable for RAGAnything processing"""
        text_chunks = []

        # Add dataset summary as first chunk
        if self.config.include_summary:
            summary = self.generate_dataset_summary(df)
            text_chunks.append(summary)

        # Process data in chunks
        for i in range(0, len(df), self.config.chunk_size):
            chunk_df = df.iloc[i : i + self.config.chunk_size]

            if self.config.convert_to_text:
                # Convert chunk to natural language
                chunk_text = self._dataframe_chunk_to_text(chunk_df, i)
            else:
                # Convert chunk to structured text (JSON-like)
                chunk_text = self._dataframe_chunk_to_structured_text(chunk_df, i)

            text_chunks.append(chunk_text)

        self.logger.info(f"Created {len(text_chunks)} text chunks from DataFrame")
        return text_chunks

    def _dataframe_chunk_to_text(self, chunk_df: pd.DataFrame, start_index: int) -> str:
        """Convert a DataFrame chunk to natural language text"""
        text_parts = []
        text_parts.append(
            f"Data Records {start_index + 1} to {start_index + len(chunk_df)}:"
        )

        for idx, row in chunk_df.iterrows():
            record_parts = []
            for col, value in row.items():
                if pd.notna(value):  # Skip null values
                    record_parts.append(f"{col} is {value}")

            if record_parts:
                record_text = f"Record {idx + 1}: " + ", ".join(record_parts) + "."
                text_parts.append(record_text)

        return "\n".join(text_parts)

    def _dataframe_chunk_to_structured_text(
        self, chunk_df: pd.DataFrame, start_index: int
    ) -> str:
        """Convert a DataFrame chunk to structured text format"""
        text_parts = []
        text_parts.append(f"Data Chunk {start_index // self.config.chunk_size + 1}:")
        text_parts.append(f"Rows {start_index + 1} to {start_index + len(chunk_df)}")

        # Convert to JSON for structured representation
        chunk_json = chunk_df.to_json(orient="records", indent=2)
        text_parts.append("Data:")
        text_parts.append(chunk_json)

        return "\n".join(text_parts)

    def get_dataframe_metadata(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Get metadata about the DataFrame"""
        metadata = {
            "shape": df.shape,
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "memory_usage": df.memory_usage(deep=True).sum(),
            "null_counts": df.isnull().sum().to_dict(),
        }

        # Add basic statistics for numeric columns
        numeric_cols = df.select_dtypes(include=["number"]).columns
        if len(numeric_cols) > 0:
            metadata["numeric_statistics"] = df[numeric_cols].describe().to_dict()

        return metadata


class ExcelRAGIntegration:
    """Integration layer between Excel processing and RAGAnything"""

    def __init__(
        self, rag_anything_instance, excel_config: ExcelProcessingConfig = None
    ):
        self.rag_anything = rag_anything_instance
        self.excel_processor = ExcelDataProcessor(excel_config)
        self.logger = logger

    async def process_excel_file(
        self, file_path: str, doc_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process an Excel file and insert it into RAGAnything"""
        try:
            # Ensure RAGAnything is initialized
            init_result = await self.rag_anything._ensure_lightrag_initialized()
            if not init_result["success"]:
                return init_result

            # Load Excel data
            df = self.excel_processor.load_excel_data(file_path)

            # Convert to text chunks
            text_chunks = self.excel_processor.convert_dataframe_to_text_chunks(df)

            # Get metadata
            metadata = self.excel_processor.get_dataframe_metadata(df)

            # Create document ID if not provided
            if doc_id is None:
                doc_id = f"excel_{Path(file_path).stem}"

            # Insert text chunks into LightRAG
            combined_text = "\n\n".join(text_chunks)

            self.logger.info(
                f"Inserting Excel data into LightRAG: {len(combined_text)} characters"
            )
            await self.rag_anything.lightrag.ainsert(combined_text)

            return {
                "success": True,
                "doc_id": doc_id,
                "metadata": metadata,
                "chunks_created": len(text_chunks),
                "total_rows": len(df),
                "columns": list(df.columns),
            }

        except Exception as e:
            error_msg = f"Error processing Excel file {file_path}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}

    async def process_dataframe_directly(
        self, df: pd.DataFrame, doc_id: str
    ) -> Dict[str, Any]:
        """Process a pandas DataFrame directly (for when you already have loaded data)"""
        try:
            # Ensure RAGAnything is initialized
            init_result = await self.rag_anything._ensure_lightrag_initialized()
            if not init_result["success"]:
                return init_result

            # Convert to text chunks
            text_chunks = self.excel_processor.convert_dataframe_to_text_chunks(df)

            # Get metadata
            metadata = self.excel_processor.get_dataframe_metadata(df)

            # Insert text chunks into LightRAG
            combined_text = "\n\n".join(text_chunks)

            self.logger.info(
                f"Inserting DataFrame data into LightRAG: {len(combined_text)} characters"
            )
            await self.rag_anything.lightrag.ainsert(combined_text)

            return {
                "success": True,
                "doc_id": doc_id,
                "metadata": metadata,
                "chunks_created": len(text_chunks),
                "total_rows": len(df),
                "columns": list(df.columns),
            }

        except Exception as e:
            error_msg = f"Error processing DataFrame {doc_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}


# Convenience function for direct integration with your existing code
async def process_excel_with_raganything(
    file_path: str,
    rag_anything_instance,
    max_rows: Optional[int] = 500,  # Default to 500 rows as in your example
    convert_to_text: bool = True,
    include_summary: bool = True,
) -> Dict[str, Any]:
    """
    Convenience function to process Excel file with RAGAnything

    This function replicates your pandas workflow but integrates with RAGAnything:
    1. Load Excel data (like your load_data() function)
    2. Limit data if specified (like your limited_data)
    3. Convert and insert into RAGAnything for querying

    Args:
        file_path: Path to Excel file
        rag_anything_instance: Your RAGAnything instance
        max_rows: Maximum number of rows to process (like head(500))
        convert_to_text: Whether to convert to natural language
        include_summary: Whether to include dataset summary

    Returns:
        Dict with processing results
    """
    excel_config = ExcelProcessingConfig(
        max_rows=max_rows,
        convert_to_text=convert_to_text,
        include_summary=include_summary,
        chunk_size=100,  # Process in smaller chunks for better retrieval
    )

    integration = ExcelRAGIntegration(rag_anything_instance, excel_config)
    return await integration.process_excel_file(file_path)
