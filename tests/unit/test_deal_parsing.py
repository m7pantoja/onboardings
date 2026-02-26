"""Tests para parse_deal_name y extract_technicians."""

import pytest

from src.models.onboarding import TechnicianInfo
from src.services.deal_detector import extract_technicians, parse_deal_name


class TestParseDealName:
    def test_standard_separator(self):
        company, service = parse_deal_name("ACME SA - CFO")
        assert company == "ACME SA"
        assert service == "CFO"

    def test_compact_separator(self):
        company, service = parse_deal_name("ACME SA-CFO")
        assert company == "ACME SA"
        assert service == "CFO"

    def test_extra_dashes_in_service(self):
        """Guiones extra quedan en el nombre del servicio (maxsplit=1)."""
        company, service = parse_deal_name("EMPRESA - ENISA - NEXT")
        assert company == "EMPRESA"
        assert service == "ENISA - NEXT"

    def test_strips_whitespace(self):
        company, service = parse_deal_name("  EMPRESA  -  CFO  ")
        assert company == "EMPRESA"
        assert service == "CFO"

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="No se pudo parsear"):
            parse_deal_name("SIN SEPARADOR")

    def test_empty_parts_raises(self):
        with pytest.raises(ValueError):
            parse_deal_name("-")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_deal_name("")

    def test_real_deal_names(self):
        """Nombres reales de deals de LeanFinance."""
        # Formato con espacios
        c, s = parse_deal_name("TURITOP SL - Financiación Pública")
        assert c == "TURITOP SL"
        assert s == "Financiación Pública"

        # Formato compacto
        c, s = parse_deal_name("NAIZ BESPOKE-CFO")
        assert c == "NAIZ BESPOKE"
        assert s == "CFO"


class TestExtractTechnicians:
    def test_extracts_non_null_properties(self):
        props = {
            "cfo_asignado": "12345",
            "tecnico_enisa_asignado": None,
            "asesor_fiscal_asignado": "",
        }
        result = extract_technicians(props)
        assert len(result) == 1
        assert result[0] == TechnicianInfo(
            hubspot_tec_id="12345", property_name="cfo_asignado"
        )

    def test_multiple_technicians(self):
        props = {
            "cfo_asignado": "111",
            "cfo_asignado_ii": "222",
            "asesor_fiscal_asignado": "333",
        }
        result = extract_technicians(props)
        assert len(result) == 3

    def test_empty_props(self):
        assert extract_technicians({}) == []

    def test_all_null(self):
        props = {
            "tecnico_enisa_asignado": None,
            "cfo_asignado": None,
        }
        assert extract_technicians(props) == []
