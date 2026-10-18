"""Seed the database with default step types and analysis types."""
from backend.models import ProcessStepType, AnalysisType

PROCESS_STEP_TYPES = [
    {
        "name": "Deposition",
        "description": "Thin film deposition (sputtering, evaporation, CVD, ALD, etc.)",
        "parameter_schema": [
            {"key": "technique",         "label": "Technique",              "type": "text",   "unit": "",    "required": True,  "placeholder": "e.g. RF sputtering, e-beam evaporation"},
            {"key": "target_material",   "label": "Target / Source",        "type": "text",   "unit": "",    "required": False, "placeholder": "e.g. TiN, Al2O3"},
            {"key": "substrate_temp",    "label": "Substrate Temperature",  "type": "number", "unit": "°C",  "required": False},
            {"key": "base_pressure",     "label": "Base Pressure",          "type": "number", "unit": "mbar","required": False},
            {"key": "process_pressure",  "label": "Process Pressure",       "type": "number", "unit": "mbar","required": False},
            {"key": "power",             "label": "Power",                  "type": "number", "unit": "W",   "required": False},
            {"key": "atmosphere",        "label": "Atmosphere / Gas",       "type": "text",   "unit": "",    "required": False, "placeholder": "e.g. Ar 50 sccm, N2/Ar"},
            {"key": "deposition_rate",   "label": "Deposition Rate",        "type": "number", "unit": "nm/s","required": False},
            {"key": "thickness",         "label": "Target Thickness",       "type": "number", "unit": "nm",  "required": False},
            {"key": "duration",          "label": "Duration",               "type": "number", "unit": "min", "required": False},
        ],
    },
    {
        "name": "Annealing",
        "description": "Thermal annealing in furnace or RTA",
        "parameter_schema": [
            {"key": "technique",      "label": "Technique",        "type": "text",   "unit": "",    "required": False, "placeholder": "e.g. RTA, tube furnace"},
            {"key": "temperature",    "label": "Temperature",      "type": "number", "unit": "°C",  "required": True},
            {"key": "duration",       "label": "Duration",         "type": "number", "unit": "min", "required": True},
            {"key": "atmosphere",     "label": "Atmosphere",       "type": "text",   "unit": "",    "required": False, "placeholder": "e.g. N2, Ar, air, vacuum"},
            {"key": "ramp_rate",      "label": "Ramp Rate",        "type": "number", "unit": "°C/min","required": False},
            {"key": "cooling",        "label": "Cooling",          "type": "text",   "unit": "",    "required": False, "placeholder": "e.g. furnace, quench"},
        ],
    },
    {
        "name": "Ion Implantation",
        "description": "Ion beam implantation",
        "parameter_schema": [
            {"key": "ion_species",    "label": "Ion Species",      "type": "text",   "unit": "",        "required": True,  "placeholder": "e.g. N+, Ar+, Fe+"},
            {"key": "energy",         "label": "Energy",           "type": "number", "unit": "keV",     "required": True},
            {"key": "fluence",        "label": "Fluence",          "type": "number", "unit": "ions/cm²","required": True},
            {"key": "flux",           "label": "Flux",             "type": "number", "unit": "ions/cm²/s","required": False},
            {"key": "tilt_angle",     "label": "Tilt Angle",       "type": "number", "unit": "°",       "required": False},
            {"key": "temperature",    "label": "Sample Temperature","type": "number", "unit": "°C",     "required": False},
            {"key": "beam_current",   "label": "Beam Current",     "type": "number", "unit": "µA",      "required": False},
        ],
    },
    {
        "name": "Lithography",
        "description": "Optical or e-beam lithography patterning",
        "parameter_schema": [
            {"key": "technique",      "label": "Technique",        "type": "text",   "unit": "",    "required": True,  "placeholder": "e.g. UV, e-beam, nanoimprint"},
            {"key": "resist",         "label": "Resist",           "type": "text",   "unit": "",    "required": False},
            {"key": "exposure_dose",  "label": "Exposure Dose",    "type": "number", "unit": "µC/cm²","required": False},
            {"key": "developer",      "label": "Developer",        "type": "text",   "unit": "",    "required": False},
            {"key": "notes_process",  "label": "Process Notes",    "type": "text",   "unit": "",    "required": False},
        ],
    },
    {
        "name": "Etching",
        "description": "Wet or dry etching",
        "parameter_schema": [
            {"key": "technique",      "label": "Technique",        "type": "text",   "unit": "",    "required": True,  "placeholder": "e.g. RIE, wet HF, ICP"},
            {"key": "chemistry",      "label": "Chemistry / Etchant","type": "text", "unit": "",    "required": False, "placeholder": "e.g. SF6/O2, HF:H2O 1:10"},
            {"key": "power",          "label": "Power",            "type": "number", "unit": "W",   "required": False},
            {"key": "pressure",       "label": "Pressure",         "type": "number", "unit": "mbar","required": False},
            {"key": "duration",       "label": "Duration",         "type": "number", "unit": "s",   "required": False},
            {"key": "etch_rate",      "label": "Etch Rate",        "type": "number", "unit": "nm/min","required": False},
        ],
    },
    {
        "name": "Other Process",
        "description": "Any other process step",
        "parameter_schema": [
            {"key": "description",    "label": "Description",      "type": "text",   "unit": "",    "required": True},
            {"key": "parameters",     "label": "Parameters",       "type": "text",   "unit": "",    "required": False},
        ],
    },
]

ANALYSIS_TYPES = [
    {
        "name": "XRD",
        "description": "X-ray Diffraction",
        "parameter_schema": [
            {"key": "mode",           "label": "Mode",             "type": "text",   "unit": "",    "placeholder": "e.g. θ-2θ, GIXRD, rocking curve"},
            {"key": "source",         "label": "X-ray Source",     "type": "text",   "unit": "",    "placeholder": "e.g. Cu Kα, Mo Kα"},
            {"key": "range_2theta",   "label": "2θ Range",         "type": "text",   "unit": "°",   "placeholder": "e.g. 20–80"},
            {"key": "step_size",      "label": "Step Size",        "type": "number", "unit": "°"},
            {"key": "incident_angle", "label": "Incident Angle (GIXRD)","type": "number","unit": "°"},
        ],
    },
    {
        "name": "XPS",
        "description": "X-ray Photoelectron Spectroscopy",
        "parameter_schema": [
            {"key": "source",         "label": "X-ray Source",     "type": "text",   "unit": "",  "placeholder": "e.g. Al Kα"},
            {"key": "elements",       "label": "Elements Surveyed", "type": "text",  "unit": ""},
            {"key": "depth_profile",  "label": "Depth Profile",    "type": "text",   "unit": "",  "placeholder": "yes/no, sputter conditions"},
        ],
    },
    {
        "name": "SEM",
        "description": "Scanning Electron Microscopy",
        "parameter_schema": [
            {"key": "accelerating_voltage","label": "Accelerating Voltage","type": "number","unit": "kV"},
            {"key": "detector",       "label": "Detector",         "type": "text",   "unit": "",  "placeholder": "e.g. SE, BSE, EDX"},
            {"key": "magnification",  "label": "Magnification",    "type": "number", "unit": "x"},
            {"key": "cross_section",  "label": "Cross Section",    "type": "text",   "unit": "",  "placeholder": "yes/no"},
        ],
    },
    {
        "name": "TEM",
        "description": "Transmission Electron Microscopy",
        "parameter_schema": [
            {"key": "accelerating_voltage","label": "Accelerating Voltage","type": "number","unit": "kV"},
            {"key": "mode",           "label": "Mode",             "type": "text",   "unit": "",  "placeholder": "e.g. BF, HAADF, SAED"},
            {"key": "sample_prep",    "label": "Sample Prep",      "type": "text",   "unit": "",  "placeholder": "e.g. FIB, ion milling"},
        ],
    },
    {
        "name": "RBS",
        "description": "Rutherford Backscattering Spectrometry",
        "parameter_schema": [
            {"key": "ion",            "label": "Ion",              "type": "text",   "unit": "",  "placeholder": "e.g. He+, H+"},
            {"key": "energy",         "label": "Beam Energy",      "type": "number", "unit": "MeV"},
            {"key": "detector_angle", "label": "Detector Angle",   "type": "number", "unit": "°"},
            {"key": "channeling",     "label": "Channeling",       "type": "text",   "unit": "",  "placeholder": "yes/no, axis"},
        ],
    },
    {
        "name": "AFM",
        "description": "Atomic Force Microscopy",
        "parameter_schema": [
            {"key": "mode",           "label": "Mode",             "type": "text",   "unit": "",  "placeholder": "e.g. tapping, contact, PFM"},
            {"key": "scan_area",      "label": "Scan Area",        "type": "text",   "unit": "µm","placeholder": "e.g. 5×5"},
            {"key": "rms_roughness",  "label": "RMS Roughness",    "type": "number", "unit": "nm"},
        ],
    },
    {
        "name": "Raman",
        "description": "Raman Spectroscopy",
        "parameter_schema": [
            {"key": "laser_wavelength","label": "Laser Wavelength","type": "number", "unit": "nm"},
            {"key": "power",          "label": "Laser Power",      "type": "number", "unit": "mW"},
            {"key": "range",          "label": "Wavenumber Range", "type": "text",   "unit": "cm⁻¹"},
        ],
    },
    {
        "name": "Hall / 4-probe",
        "description": "Electrical measurements (Hall effect, 4-probe resistivity)",
        "parameter_schema": [
            {"key": "technique",      "label": "Technique",        "type": "text",   "unit": "",  "placeholder": "e.g. van der Pauw, 4-probe"},
            {"key": "temperature",    "label": "Temperature",      "type": "number", "unit": "K"},
            {"key": "magnetic_field", "label": "Magnetic Field",   "type": "number", "unit": "T"},
            {"key": "carrier_density","label": "Carrier Density",  "type": "number", "unit": "cm⁻³"},
            {"key": "mobility",       "label": "Mobility",         "type": "number", "unit": "cm²/Vs"},
            {"key": "resistivity",    "label": "Resistivity",      "type": "number", "unit": "Ω·cm"},
        ],
    },
    {
        "name": "Ellipsometry",
        "description": "Spectroscopic or single-wavelength ellipsometry",
        "parameter_schema": [
            {"key": "wavelength_range","label": "Wavelength Range","type": "text",   "unit": "nm"},
            {"key": "angle",          "label": "Angle of Incidence","type": "number","unit": "°"},
            {"key": "thickness",      "label": "Measured Thickness","type": "number","unit": "nm"},
            {"key": "model",          "label": "Optical Model",    "type": "text",   "unit": ""},
        ],
    },
    {
        "name": "SIMS",
        "description": "Secondary Ion Mass Spectrometry",
        "parameter_schema": [
            {"key": "primary_ion",    "label": "Primary Ion",      "type": "text",   "unit": "",  "placeholder": "e.g. Cs+, O2+"},
            {"key": "primary_energy", "label": "Primary Energy",   "type": "number", "unit": "keV"},
            {"key": "elements",       "label": "Elements Detected", "type": "text",  "unit": ""},
            {"key": "depth_profile",  "label": "Depth Profile",    "type": "text",   "unit": "",  "placeholder": "yes/no"},
        ],
    },
    {
        "name": "Other Analysis",
        "description": "Any other analysis technique",
        "parameter_schema": [
            {"key": "technique",      "label": "Technique",        "type": "text",   "unit": "",  "required": True},
            {"key": "parameters",     "label": "Parameters",       "type": "text",   "unit": ""},
        ],
    },
]


async def seed_types(session):
    from sqlalchemy import select
    # Seed process step types
    for data in PROCESS_STEP_TYPES:
        result = await session.execute(
            select(ProcessStepType).where(ProcessStepType.name == data["name"])
        )
        if not result.scalar_one_or_none():
            session.add(ProcessStepType(**data))

    # Seed analysis types
    for data in ANALYSIS_TYPES:
        result = await session.execute(
            select(AnalysisType).where(AnalysisType.name == data["name"])
        )
        if not result.scalar_one_or_none():
            session.add(AnalysisType(**data))

    await session.commit()
