"""Tests for ScriptedNavigator - IVR menu extraction and DTMF navigation."""

from app.services.ai.ivr.navigator import NavigationAction, ScriptedNavigator


class TestExtractMenuOptions:
    """Tests for extract_menu_options()."""

    def test_press_x_for_y(self):
        """'Press 1 for sales' pattern."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options("Press 1 for sales. Press 2 for support.")
        digits = {o.digit for o in options}
        assert "1" in digits
        assert "2" in digits

    def test_for_y_press_x(self):
        """'For sales, press 1' pattern."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options("For sales, press 1. For billing, press 2.")
        digits = {o.digit for o in options}
        assert "1" in digits
        assert "2" in digits

    def test_to_y_press_x(self):
        """'To speak to a representative, press 0' pattern."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options("To speak to a representative, press 0.")
        digits = {o.digit for o in options}
        assert "0" in digits

    def test_option_x_for_y(self):
        """'Option 1 for billing' pattern."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options("Option 1 for billing. Option 2 for tech support.")
        digits = {o.digit for o in options}
        assert "1" in digits
        assert "2" in digits

    def test_say_or_press_x(self):
        """'Say or press 1 for sales' pattern."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options("Say or press 1 for sales. Say or press 2 for support.")
        digits = {o.digit for o in options}
        assert "1" in digits
        assert "2" in digits

    def test_star_and_pound(self):
        """Star and pound keys should be normalized."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options(
            "Press star for the operator. Press pound for the directory."
        )
        digits = {o.digit for o in options}
        assert "*" in digits
        assert "#" in digits

    def test_no_menu_options(self):
        """Non-menu text should return empty list."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options("Hello, how can I help you?")
        assert options == []

    def test_deduplication(self):
        """Same digit mentioned twice should only appear once."""
        nav = ScriptedNavigator()
        options = nav.extract_menu_options("Press 1 for sales. For orders, press 1.")
        digits = [o.digit for o in options]
        assert digits.count("1") == 1


class TestSelectDigit:
    """Tests for select_digit() decision algorithm."""

    def test_goal_match_sales(self):
        """Should match 'sales' digit when goal mentions sales."""
        nav = ScriptedNavigator(navigation_goal="Reach the sales department")
        result = nav.select_digit("Press 1 for sales. Press 2 for support.")
        assert result.action == NavigationAction.PRESS_DIGIT
        assert result.digit == "1"
        assert "goal match" in result.reason

    def test_goal_match_support(self):
        """Should match 'support' digit when goal mentions help."""
        nav = ScriptedNavigator(navigation_goal="Get technical help")
        result = nav.select_digit("Press 1 for sales. Press 2 for support.")
        assert result.action == NavigationAction.PRESS_DIGIT
        assert result.digit == "2"

    def test_goal_match_human(self):
        """Should match 'representative' when goal is reaching a human."""
        nav = ScriptedNavigator(navigation_goal="Reach a human representative")
        result = nav.select_digit("Press 1 for billing. Press 0 for a representative.")
        assert result.action == NavigationAction.PRESS_DIGIT
        assert result.digit == "0"

    def test_fallback_to_operator(self):
        """When no goal match, should try 0 (operator)."""
        nav = ScriptedNavigator(navigation_goal="Reach a human representative")
        # No matching options in text
        result = nav.select_digit("Welcome to our phone system.")
        assert result.action == NavigationAction.PRESS_DIGIT
        assert result.digit == "0"
        assert "operator" in result.reason

    def test_fallback_to_untried_options(self):
        """After operator tried, should try untried extracted options."""
        nav = ScriptedNavigator(navigation_goal="Discuss pricing")
        nav.record_attempt("0")  # Mark operator as tried

        result = nav.select_digit("Press 1 for hours. Press 2 for locations.")
        assert result.action == NavigationAction.PRESS_DIGIT
        assert result.digit in {"1", "2"}

    def test_fallback_sequential(self):
        """After all options and operator tried, try sequential 1-9."""
        nav = ScriptedNavigator(navigation_goal="Reach someone")
        # Mark a bunch as tried
        for d in "0":
            nav.record_attempt(d)

        result = nav.select_digit("Thank you for calling.")  # No menu options
        assert result.action == NavigationAction.PRESS_DIGIT
        assert result.digit == "1"  # First sequential

    def test_exhausted_returns_fallback_ai(self):
        """When max attempts exceeded, return FALLBACK_AI."""
        nav = ScriptedNavigator(navigation_goal="Reach a human", max_attempts=2)
        # Exhaust attempts
        nav.select_digit("Press 1 for sales.")
        nav.record_attempt("1")
        nav.select_digit("Press 1 for sales.")
        nav.record_attempt("0")

        result = nav.select_digit("Press 1 for sales.")
        assert result.action == NavigationAction.FALLBACK_AI
        assert "max attempts" in result.reason

    def test_all_digits_exhausted(self):
        """When all digits 0-9 are tried, return FALLBACK_AI."""
        nav = ScriptedNavigator(navigation_goal="Reach someone", max_attempts=20)
        for d in "0123456789":
            nav.record_attempt(d)

        result = nav.select_digit("Welcome to our system.")
        assert result.action == NavigationAction.FALLBACK_AI
        assert "exhausted" in result.reason

    def test_skips_already_attempted(self):
        """Should not suggest digits already attempted."""
        nav = ScriptedNavigator(navigation_goal="Reach sales department")
        nav.record_attempt("1")

        result = nav.select_digit("Press 1 for sales. Press 2 for support.")
        assert result.digit != "1"

    def test_record_attempt_and_failure(self):
        """record_attempt and record_failure should track state."""
        nav = ScriptedNavigator()
        nav.record_attempt("1")
        nav.record_failure("1")
        assert "1" in nav._attempted
        assert "1" in nav._failed


class TestSynonymExpansion:
    """Tests for keyword synonym expansion."""

    def test_human_synonyms(self):
        """'human' should expand to representative, agent, operator, etc."""
        keywords = ScriptedNavigator._expand_keywords("reach a human")
        assert "representative" in keywords
        assert "agent" in keywords
        assert "operator" in keywords

    def test_sales_synonyms(self):
        """'sales' should expand to sell, purchase, buy, etc."""
        keywords = ScriptedNavigator._expand_keywords("talk to sales")
        assert "sell" in keywords
        assert "purchase" in keywords

    def test_appointment_synonyms(self):
        """'appointment' should expand to schedule, booking, etc."""
        keywords = ScriptedNavigator._expand_keywords("make an appointment")
        assert "schedule" in keywords
        assert "booking" in keywords

    def test_no_expansion_for_unknown_words(self):
        """Unknown words should not get expanded."""
        keywords = ScriptedNavigator._expand_keywords("foobar bazqux")
        assert keywords == {"foobar", "bazqux"}
