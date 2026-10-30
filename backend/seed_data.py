"""Default step types, analysis types and dropdown values (field types: see
backend/params.py), seeded into a new database by seed.py."""
from backend.params import with_equipment


def num(key, label, unit="", **kw):
    return {"key": key, "label": label, "type": "number", "unit": unit, **kw}


def duration(key, label, **kw):
    return {"key": key, "label": label, "type": "duration", "unit": "min:s", **kw}


def text(key, label, **kw):
    return {"key": key, "label": label, "type": "text", **kw}


def longtext(key, label, **kw):
    return {"key": key, "label": label, "type": "longtext", **kw}


def choice(key, label, list=None, **kw):
    return {"key": key, "label": label, "type": "choice", "list": list or key, **kw}


def check(key, label, fields):
    return {"key": key, "label": label, "type": "check", "fields": fields}


def variant(key, label, options: dict):
    return {"key": key, "label": label, "type": "variant",
            "options": [{"value": value, "fields": fields} for value, fields in options.items()]}


def modes(key, label, list, fields):
    return {"key": key, "label": label, "type": "modes", "list": list, "fields": fields}


PROCESS_STEP_TYPES = [
    {
        "name": "Deposition",
        "description": "Thin film deposition (sputtering, evaporation, …)",
        "parameter_schema": [
            choice("machine", "Machine", located=True),
            choice("technique", "Technique", "deposition_technique"),
            choice("target", "Target"),
            choice("atmosphere", "Atmosphere"),
            num("base_pressure", "Base pressure", "mTorr", placeholder="e.g. 1e-4"),
            num("working_pressure", "Working pressure", "mTorr", placeholder="e.g. 3"),
            num("power", "Power", "W"),
            num("gas_flow", "Gas flow", "sccm", placeholder="e.g. 20, or 20/5 for Ar/O2"),
            duration("duration", "Duration", placeholder="e.g. 12:30"),
            text("station", "Station"),
            num("deposition_rate", "Deposition rate", "nm/min", placeholder="if known"),
            num("thickness", "Thickness", "nm", placeholder="if known"),
            check("calibration", "Calibration sample", [
                longtext("calibration_details", "Calibration sample details",
                         placeholder="Substrate, number of pieces, whether they were marked, …"),
            ]),
        ],
    },
    {
        "name": "Annealing",
        "description": "Thermal annealing in a furnace or RTA",
        "parameter_schema": [
            variant("method", "Method", {
                "Furnace": [
                    num("temperature", "Temperature", "°C"),
                    num("duration", "Duration", "min"),
                ],
                "RTA": [
                    choice("atmosphere", "Atmosphere"),
                    num("temperature", "Temperature", "°C"),
                    num("duration", "Duration", "s"),
                    num("ramp", "Ramp", "°C/s"),
                ],
            }),
        ],
    },
    {
        "name": "Ion Implantation",
        "description": "Ion beam implantation",
        "parameter_schema": [
            choice("ion", "Ion", "ion_species"),
            num("energy", "Energy", "keV"),
            num("fluence", "Fluence", "ions/cm²", placeholder="e.g. 1e16"),
            num("flux", "Flux", "ions/cm²/s"),
            num("tilt_angle", "Tilt angle", "°"),
            num("temperature", "Sample temperature", "°C"),
            num("beam_current", "Beam current", "µA"),
        ],
    },
    {
        "name": "Lithography",
        "description": "Optical or e-beam lithography patterning",
        "parameter_schema": [
            variant("method", "Method", {
                "Optical": [
                    text("mask", "Mask"),
                    num("exposure_dose", "Exposure dose", "mJ/cm²"),
                    num("exposure_time", "Exposure time", "s"),
                ],
                "E-beam": [
                    num("dose", "Dose", "µC/cm²"),
                    num("voltage", "Acceleration voltage", "kV"),
                ],
            }),
            choice("resist", "Resist"),
            choice("developer", "Developer"),
            num("development_time", "Development time", "s"),
        ],
    },
    {
        "name": "Etching",
        "description": "Wet or dry etching",
        "parameter_schema": [
            variant("method", "Method", {
                "Dry": [
                    choice("technique", "Technique", "dry_etch_technique"),
                    choice("gases", "Gases", "etch_gas"),
                    num("power", "Power", "W"),
                    num("pressure", "Pressure", "mTorr"),
                ],
                "Wet": [
                    choice("etchant", "Etchant"),
                    num("temperature", "Temperature", "°C"),
                ],
            }),
            num("duration", "Duration", "s"),
            num("etch_rate", "Etch rate", "nm/min", placeholder="if known"),
        ],
    },
    {
        "name": "CMP",
        "description": "Chemical mechanical polishing",
        "parameter_schema": [
            choice("slurry", "Slurry type", "cmp_slurry"),
            num("abrasive_size", "Abrasive size", "nm"),
            num("abrasive_concentration", "Abrasive concentration", "wt%"),
            num("ph", "pH"),
            text("dilution", "Dilution", placeholder="e.g. 1:10 with DI water"),
            num("slurry_flow", "Slurry flow", "mL/min"),
            choice("pad", "Pad type", "cmp_pad"),
            num("force", "Force", "N"),
            num("back_pressure", "Back pressure", "psi"),
            num("platen_speed", "Platen speed", "rpm"),
            num("carrier_speed", "Carrier speed", "rpm"),
            duration("duration", "Time", placeholder="e.g. 12:30"),
            num("temperature", "Temperature", "°C"),
            check("conditioning", "Pad conditioning", [
                longtext("conditioning_details", "Conditioning details",
                         placeholder="In situ or ex situ, conditioner, force, time, …"),
            ]),
            num("thickness_removed", "Thickness removed", "nm", placeholder="if known"),
            num("removal_rate", "Removal rate", "nm/min", placeholder="if known"),
            longtext("post_clean", "Post-CMP clean", placeholder="Rinse, brush, megasonic, chemistry, …"),
        ],
    },
    {
        "name": "Cut",
        "description": "Cutting the sample into pieces (each piece becomes its own sample)",
        "parameter_schema": [
            choice("method", "Method", "cut_method"),
            num("pieces", "Pieces"),
        ],
    },
    {
        "name": "Devices made",
        "description": "The process is done and the devices on the sample are ready (each device is listed on the sample)",
        "parameter_schema": [],
    },
    {
        "name": "Other Process",
        "description": "Any other process step",
        "parameter_schema": [
            longtext("description", "Description"),
        ],
    },
]

ANALYSIS_TYPES = [
    {
        "name": "XRD / HRXRD",
        "description": "X-ray diffraction or high-resolution X-ray diffraction",
        "parameter_schema": [
            variant("instrument", "Instrument", {"XRD": [], "HRXRD": []}),
            modes("modes", "Modes", "xrd_mode", [
                text("range", "Range", placeholder="e.g. 2θ 20–80°"),
                num("step", "Step", "°"),
                num("time", "Acquisition time", "s/step"),
                longtext("configuration", "Configuration",
                         placeholder="Soller slits, divergence/receiving slits, monochromator, …"),
            ]),
        ],
    },
    {
        "name": "XPS",
        "description": "X-ray Photoelectron Spectroscopy",
        "parameter_schema": [
            choice("source", "X-ray source", "xps_source"),
            text("elements", "Elements surveyed"),
            text("depth_profile", "Depth profile", placeholder="sputter conditions, if any"),
        ],
    },
    {
        "name": "Optical Microscopy",
        "description": "Optical microscope inspection",
        "parameter_schema": [
            choice("mode", "Mode", "optical_mode"),
            text("magnification", "Magnification(s)", placeholder="e.g. 5×, 20×, 50×"),
            longtext("observations", "Observations", placeholder="Defects, cracks, particles, colour uniformity, …"),
        ],
    },
    {
        "name": "SEM",
        "description": "Scanning Electron Microscopy",
        "parameter_schema": [
            choice("equipment", "Equipment", "sem_equipment", located=True),
        ],
    },
    {
        "name": "TEM",
        "description": "Transmission Electron Microscopy",
        "parameter_schema": [
            num("voltage", "Accelerating voltage", "kV"),
            text("mode", "Mode", placeholder="e.g. BF, HAADF, SAED"),
            text("sample_prep", "Sample preparation", placeholder="e.g. FIB, ion milling"),
        ],
    },
    {
        "name": "RBS",
        "description": "Rutherford Backscattering Spectrometry, with or without channeling",
        "parameter_schema": [
            variant("technique", "Technique", {
                "RBS": [],
                "RBS/Channeling": [
                    text("axis", "Channeling axis", placeholder="e.g. <0001>"),
                    longtext("angular_scans", "Angular scans"),
                ],
            }),
            choice("ion", "Ion", "ion_beam"),
            num("energy", "Beam energy", "MeV"),
            longtext("detectors", "Detectors", placeholder="Angle and type of each detector"),
            longtext("charge", "Charge per acquisition", placeholder="Charge used in each acquisition"),
        ],
    },
    {
        "name": "AFM",
        "description": "Atomic Force Microscopy",
        "parameter_schema": [
            choice("mode", "Mode", "afm_mode"),
            text("scan_area", "Scan area", placeholder="e.g. 5×5 µm"),
            num("rms_roughness", "RMS roughness", "nm"),
        ],
    },
    {
        "name": "Raman",
        "description": "Raman Spectroscopy",
        "parameter_schema": [
            num("laser_wavelength", "Laser wavelength", "nm"),
            num("power", "Laser power", "mW"),
            text("range", "Range", placeholder="e.g. 100–1200 cm⁻¹"),
        ],
    },
    {
        "name": "Hall / 4-probe",
        "description": "Electrical measurements (Hall effect, 4-probe resistivity)",
        "parameter_schema": [
            variant("technique", "Technique", {
                "Hall": [
                    num("magnetic_field", "Magnetic field", "T"),
                    num("carrier_density", "Carrier density", "cm⁻³"),
                    num("mobility", "Mobility", "cm²/Vs"),
                ],
                "4-probe": [],
            }),
            num("temperature", "Temperature", "K"),
            num("resistivity", "Resistivity", "Ω·cm"),
        ],
    },
    {
        "name": "Ellipsometry",
        "description": "Spectroscopic or single-wavelength ellipsometry",
        "parameter_schema": [
            text("wavelength_range", "Wavelength range", placeholder="e.g. 250–1700 nm"),
            text("angles", "Angles of incidence", placeholder="e.g. 65, 70, 75°"),
            num("thickness", "Thickness", "nm"),
            longtext("detector_settings", "Detector settings", placeholder="Gain, integration time, slit width, …"),
            check("reference", "Reference taken", [
                longtext("reference_details", "Reference details",
                         placeholder="What was used as reference (air, bare substrate, …) and when it was taken"),
            ]),
            longtext("model", "Optical model", placeholder="Layers, dispersion models, fitted parameters, MSE, …"),
        ],
    },
    {
        "name": "Profilometry",
        "description": "Stylus profilometry: step height (film thickness) and roughness",
        "parameter_schema": [
            num("thickness", "Step height / thickness", "nm"),
            num("scan_length", "Scan length", "µm"),
            num("stylus_force", "Stylus force", "mg"),
            num("scan_speed", "Scan speed", "µm/s"),
            num("roughness", "Roughness (Ra)", "nm"),
            text("positions", "Measurement positions", placeholder="e.g. 3 steps across the sample"),
        ],
    },
    {
        "name": "Other Analysis",
        "description": "Any other analysis technique",
        "parameter_schema": [
            text("technique", "Technique"),
            longtext("description", "Description"),
        ],
    },
]

# Every technique gets an Equipment dropdown tied to the place (Where), unless
# it has one already (Deposition's Machine, SEM). Cut has its own form.
for _type in PROCESS_STEP_TYPES + ANALYSIS_TYPES:
    if _type["name"] not in ("Cut", "Devices made"):
        _type["parameter_schema"] = with_equipment(_type["parameter_schema"], _type["name"])

# Starting values of the shared dropdowns; people add more as they go.
# Equipment is given as (name, place).
CHOICE_OPTIONS = {
    "location": ["CTN", "INESC MN"],
    "machine": [("Alcatel SCM 450", "INESC MN"), ("UHV1", "INESC MN"), ("UHV2", "INESC MN"), ("SentiFet", "INESC MN")],
    "deposition_technique": ["RF magnetron sputtering", "DC magnetron sputtering"],
    "atmosphere": ["Ar", "Ar + O2", "Ar + N2", "N2", "O2", "Air", "Vacuum"],
    "dry_etch_technique": ["RIE", "ICP"],
    "cmp_slurry": ["Colloidal silica", "Fumed silica", "Ceria", "Alumina"],
    "cmp_pad": ["IC1000", "IC1000/Suba IV", "Suba IV", "Politex"],
    "cut_method": ["Diamond-tipped pen", "Dicing"],
    "xrd_mode": ["2θ/ω", "Rocking curve", "Grazing incidence"],
    "xps_source": ["Al Kα", "Mg Kα"],
    "sem_equipment": ["Hitachi S-2500"],
    "ion_beam": ["He+", "H+"],
    "afm_mode": ["Tapping", "Contact"],
    "optical_mode": ["Bright field", "Dark field", "DIC", "Polarized light"],
}
