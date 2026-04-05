MEDICAL_VISION_PROMPT = """
Act as a Medical Researcher and Senior Clinician. Analyze this image in a strict medical context.
Identify the image type (e.g., Radiological Scan, Histopathology Slide, Kaplan-Meier Plot, Flowchart, Clinical Photograph).

Provide a JSON response with:
{
    "detailed_description": "Describe findings using standard medical terminology. For scans: mention modality, orientation, anatomical structures, and pathology (lesions, masses). For charts: interpret axes, significant trends, and p-values. For pathology: describe cellular architecture and staining.",
    "entity_info": {
        "entity_name": "Specific condition, anatomical region, or study result shown",
        "entity_type": "MedicalVisualEvidence",
        "summary": "Clinical significance and diagnostic implication of this visual data."
    }
}
Context: {context}
Image Info: {captions}
"""

MEDICAL_TABLE_PROMPT = """
Act as a Medical Data Analyst. Analyze this clinical data table.
Focus on:
- Patient demographics (n, age, gender distribution)
- Treatment groups and control arms
- Statistical significance (confidence intervals, p-values)
- Clinical outcomes (Adverse events, Efficacy rates)

Provide a JSON response with:
{
    "detailed_description": "Summarize the key clinical findings, statistical comparisons, and significant differences between groups.",
    "entity_info": {
        "entity_name": "Table Content Summary (e.g. Baseline Characteristics)",
        "entity_type": "ClinicalTable",
        "summary": "Key statistical evidence presented in this table."
    }
}
Context: {context}
Table Info: {table_caption}
"""

MEDICAL_ENTITY_TYPES = [
    "Disease", "Symptom", "Syndrome", "ClinicalSign",
    "Medication", "MedicalProcedure", "Therapy", "Dosage",
    "Anatomy", "Gene", "Protein", "Biomarker", "Pathogen",
    "StudyOutcome", "Metric", "PopulationGroup"
]
