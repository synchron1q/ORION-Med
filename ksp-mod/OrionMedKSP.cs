using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace OrionMedKSP
{
    #region 1. DTO-модели для парсинга JSON из ORION-MED (GET /api/state)

    [Serializable]
    public class HevStateDto
    {
        public string server_time;
        public string version;
        public string medical_status; // "NOMINAL" | "ADVISORY" | "CAUTION" | "WARNING"
        public HevModeDto mode;
        public HevMasterDto master;
        public HevParameterDto[] parameters;
        public HevAlertDto[] alerts;
        public HevRadiationDto radiation;
        public HevDonkiDto nasa_donki;
        public HevSimSpaceWeatherDto space_weather_simulation;
        public HevReadinessDto readiness;
    }

    [Serializable]
    public class HevModeDto
    {
        public bool demo_mode;
        public bool simulator_enabled;
        public string scenario; // "nominal", "hypoxia", "hemorrhage", "high_co2", "solar_flare", "tachycardia", "sensor_failure"
    }

    [Serializable]
    public class HevMasterDto
    {
        public bool warning;
        public bool warning_unacked;
        public bool caution;
        public bool caution_unacked;
        public bool audio_required;
    }

    [Serializable]
    public class HevParameterDto
    {
        public string id;
        public string label;
        public string @short;
        public string unit;
        public string category;
        public string zone;
        public string status;   // "OK", "STALE", "SENSOR_FAULT", "NO_DATA", "NOT_INSTRUMENTED"
        public float value;
        public string band;     // "NOMINAL", "ADVISORY", "CAUTION", "WARNING"
        public string fault_reason;
    }

    [Serializable]
    public class HevAlertDto
    {
        public string id;
        public string rule_id;
        public string kind;
        public string parameter;
        public string zone;
        public string title;
        public string message;
        public string severity;    // "ADVISORY", "CAUTION", "WARNING"
        public string lifecycle;   // "ACTIVE", "RECOVERY", "CLEARED"
        public string protocol_id;
        public bool acknowledged;
        public bool can_clear;
    }

    [Serializable]
    public class HevRadiationDto
    {
        public float dose_rate;
        public float accumulated_mGy;
        public float budget_mGy;
        public float budget_fraction;
    }

    [Serializable]
    public class HevDonkiDto
    {
        public string status;
        public string latest_event;
        public string space_weather_risk;
        public string eva_advisory;
    }

    [Serializable]
    public class HevSimSpaceWeatherDto
    {
        public string status;
        public string latest_event;
        public string space_weather_risk;
        public string eva_advisory;
    }

    [Serializable]
    public class HevReadinessDto
    {
        public HevEvaReadinessDto eva;
        public HevTriageDto triage;
    }

    [Serializable]
    public class HevEvaReadinessDto
    {
        public string status; // "NO_BLOCKERS" | "REVIEW" | "DATA_INCOMPLETE" | "HOLD_RECOMMENDED"
        public int gates_clear;
        public int gates_total;
    }

    [Serializable]
    public class HevTriageDto
    {
        public string focus;
        public string title;
        public string severity;
        public string alert_id;
        public string protocol_id;
        public string kit;
        public string rationale;
    }

    [Serializable]
    public class KspCrewSyncDto
    {
        public string name;
        public string trait;
        public string type;
        public bool inactive;
        public string state_label;
    }

    [Serializable]
    public class KspSyncPayloadDto
    {
        public string vessel_name;
        public string situation;
        public string body;
        public float altitude_m;
        public float g_force;
        public float mach;
        public float met_s;
        public bool eva_active;
        public string emotion;
        public string consciousness;
        public string primary_cause;
        public float critical_timer_s;
        public float lethal_limit_s;
        public bool ingest_biometrics;
        public KspCrewSyncDto[] crew;
    }

    #endregion

    #region 2. Внутренние структуры состояния и маппинга

    public enum KerbalEmotion
    {
        Joy,
        Neutral,
        Stressed,
        Panic
    }

    public enum KerbalConsciousness
    {
        Alert,
        CognitivelyImpaired,
        Unconscious,
        Dead
    }

    public class CrewEvaluationResult
    {
        public KerbalEmotion Emotion = KerbalEmotion.Neutral;
        public KerbalConsciousness Consciousness = KerbalConsciousness.Alert;
        public float WheeLevel = 0.1f;
        public float FearFactor = 0.0f;
        public float PanicLevel = 0.0f;
        public bool IsLifeThreatening = false;
        public string PrimaryCause = "All systems nominal";
    }

    #endregion

    #region 3. Основной модуль судна (VesselModule)

    public class OrionMedVesselModule : VesselModule
    {
        // Не используем [KSPField(isPersistant = true)] для URL с "//", так как парсер .sfs в KSP воспринимает "//" как комментарий и обрезает строку до "http:".
        public string ApiBaseUrl = "http://127.0.0.1:8000";

        [KSPField(isPersistant = true)]
        public float PollIntervalSeconds = 1.0f;

        [KSPField(isPersistant = true)]
        public float LethalExposureLimitSeconds = 30.0f;

        private bool _isConnected = false;
        private string _lastError = string.Empty;
        private HevStateDto _latestState;
        private readonly Dictionary<string, HevParameterDto> _paramMap =
            new Dictionary<string, HevParameterDto>(StringComparer.OrdinalIgnoreCase);

        private CrewEvaluationResult _currentEval = new CrewEvaluationResult();
        private float _criticalExposureTimer = 0f;
        private bool _pushGForceToOrion = true;
        private float _lastEvaWarningTime = 0f;
        private string _lastKspFlightPhase = "NOMINAL_PAD";

        private readonly Dictionary<string, ProtoCrewMember.KerbalType> _originalCrewTypes =
            new Dictionary<string, ProtoCrewMember.KerbalType>();

        private static FieldInfo _fiFearFactor;
        private static FieldInfo _fiWheeLevel;
        private static FieldInfo _fiPanicLevel;
        private static bool _reflectionInitialized = false;

        private Rect _windowRect = new Rect(20f, 70f, 435f, 590f);
        private bool _showGui = true;
        private Vector2 _alertsScrollPos = Vector2.zero;

        protected override void OnStart()
        {
            base.OnStart();
            if (string.IsNullOrEmpty(ApiBaseUrl) || !ApiBaseUrl.Contains("://"))
                ApiBaseUrl = "http://127.0.0.1:8000";
            InitReflection();
            StartCoroutine(PollOrionMedCoroutine());
        }

        private static void InitReflection()
        {
            if (_reflectionInitialized) return;
            _reflectionInitialized = true;

            try
            {
                Type exprType = typeof(kerbalExpressionSystem);
                BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
                _fiFearFactor = exprType.GetField("fearFactor", flags);
                _fiWheeLevel = exprType.GetField("wheeLevel", flags);
                _fiPanicLevel = exprType.GetField("panicLevel", flags);
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[ORION-MED] Ошибка инициализации рефлексии: " + ex.Message);
            }
        }

        private void Update()
        {
            if (!FlightGlobals.ready || vessel == null || !vessel.isActiveVessel)
                return;

            // Alt + M — скрыть/показать окно
            if (Input.GetKey(KeyCode.LeftAlt) && Input.GetKeyDown(KeyCode.M))
            {
                _showGui = !_showGui;
            }

            if (_isConnected && _latestState != null)
            {
                CheckFlightRegimeAlerts();
                ApplyStateToActiveCrew(Time.deltaTime);

                // Если экипаж вышел в открытый космос (EVA) при запрете EVA HOLD_RECOMMENDED
                if (vessel.isEVA &&
                    _latestState.readiness != null &&
                    _latestState.readiness.eva != null &&
                    _latestState.readiness.eva.status == "HOLD_RECOMMENDED" &&
                    Time.time - _lastEvaWarningTime > 6.0f)
                {
                    _lastEvaWarningTime = Time.time;
                    ScreenMessages.PostScreenMessage(
                        "<color=#FF2222><b>[ORION-MED // EVA CLEARANCE: NO-GO]</b> ВЫХОД В ОТКРЫТЫЙ КОСМОС ЗАПРЕЩЁН! НЕМЕДЛЕННО ВЕРНИТЕСЬ В ШЛЮЗ!</color>",
                        4.5f,
                        ScreenMessageStyle.UPPER_CENTER);
                }
            }
        }

        private void CheckFlightRegimeAlerts()
        {
            if (vessel == null) return;

            bool inVacuum = vessel.atmDensity <= 0.0001;
            bool inOrbitOrSub = vessel.situation == Vessel.Situations.ORBITING ||
                                vessel.situation == Vessel.Situations.ESCAPING ||
                                vessel.situation == Vessel.Situations.SUB_ORBITAL;
            bool inAtmosEntry = !inVacuum &&
                                (vessel.situation == Vessel.Situations.FLYING || vessel.situation == Vessel.Situations.SUB_ORBITAL) &&
                                (vessel.mach >= 1.15 || vessel.geeForce >= 1.85 || vessel.verticalSpeed < -15.0);

            string newPhase = "NOMINAL_PAD";
            if (vessel.isEVA)
                newPhase = "EVA_OPEN_SPACE";
            else if (inVacuum && (inOrbitOrSub || vessel.altitude >= 70000.0))
                newPhase = "OPEN_SPACE";
            else if (inAtmosEntry)
                newPhase = "ATMOS_ENTRY";

            if (newPhase != _lastKspFlightPhase)
            {
                _lastKspFlightPhase = newPhase;
                if (newPhase == "EVA_OPEN_SPACE")
                {
                    ScreenMessages.PostScreenMessage(
                        "<color=#FF3333><b>[ORION-MED // ТРЕВОГА ОТКРЫТОГО КОСМОСА (EVA)]</b> Выход за борт: падение SpO2 в скафандре и радиационная нагрузка!</color>",
                        6.0f,
                        ScreenMessageStyle.UPPER_CENTER);
                }
                else if (newPhase == "OPEN_SPACE")
                {
                    ScreenMessages.PostScreenMessage(
                        "<color=#FF4444><b>[ORION-MED // ТРЕВОГА ОТКРЫТОГО КОСМОСА]</b> Выход в вакуум: всплеск космической радиации и перегрузка СЖО (CO2)!</color>",
                        6.0f,
                        ScreenMessageStyle.UPPER_CENTER);
                }
                else if (newPhase == "ATMOS_ENTRY")
                {
                    ScreenMessages.PostScreenMessage(
                        "<color=#FF4444><b>[ORION-MED // ТРЕВОГА ВХОДА В АТМОСФЕРУ]</b> Высокая перегрузка и торможение: тахикардия и падение давления экипажа!</color>",
                        6.0f,
                        ScreenMessageStyle.UPPER_CENTER);
                }
            }
        }

        private IEnumerator PollOrionMedCoroutine()
        {
            var wait = new WaitForSecondsRealtime(Mathf.Max(0.25f, PollIntervalSeconds));

            while (this != null)
            {
                if (FlightGlobals.ready && vessel != null && vessel.isActiveVessel)
                {
                    if (string.IsNullOrEmpty(ApiBaseUrl) || !ApiBaseUrl.Contains("://"))
                        ApiBaseUrl = "http://127.0.0.1:8000";
                    string baseUrl = ApiBaseUrl.TrimEnd('/');
                    string stateUrl = baseUrl + "/api/state";

                    using (UnityWebRequest req = UnityWebRequest.Get(stateUrl))
                    {
                        req.timeout = 3;
                        yield return req.SendWebRequest();

                        if (req.isNetworkError || req.isHttpError)
                        {
                            _isConnected = false;
                            _lastError = !string.IsNullOrEmpty(req.error) ? req.error : ("HTTP " + req.responseCode);
                        }
                        else
                        {
                            ProcessStateJson(req.downloadHandler.text);
                        }
                    }

                    if (_isConnected && vessel != null && vessel.isActiveVessel)
                    {
                        string syncUrl = baseUrl + "/api/v1/ksp/sync";
                        string payloadJson = BuildKspSyncPayloadJson();
                        using (UnityWebRequest syncReq = new UnityWebRequest(syncUrl, "POST"))
                        {
                            syncReq.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(payloadJson));
                            syncReq.downloadHandler = new DownloadHandlerBuffer();
                            syncReq.SetRequestHeader("Content-Type", "application/json");
                            syncReq.timeout = 2;
                            yield return syncReq.SendWebRequest();
                        }
                    }
                }
                yield return wait;
            }
        }

        private string BuildKspSyncPayloadJson()
        {
            List<ProtoCrewMember> crewList = vessel.GetVesselCrew();
            List<KspCrewSyncDto> crewDtos = new List<KspCrewSyncDto>();
            if (crewList != null)
            {
                foreach (ProtoCrewMember c in crewList)
                {
                    if (c == null) continue;
                    string stateLabel = c.inactive
                        ? "UNCONSCIOUS"
                        : (c.type == ProtoCrewMember.KerbalType.Tourist ? "IMPAIRED" : "IN_COMMAND");
                    crewDtos.Add(new KspCrewSyncDto
                    {
                        name = c.name,
                        trait = c.trait,
                        type = c.type.ToString(),
                        inactive = c.inactive,
                        state_label = stateLabel
                    });
                }
            }

            KspSyncPayloadDto dto = new KspSyncPayloadDto
            {
                vessel_name = vessel.GetDisplayName(),
                situation = vessel.situation.ToString(),
                body = vessel.mainBody != null ? vessel.mainBody.bodyName : "Space",
                altitude_m = (float)vessel.altitude,
                g_force = (float)vessel.geeForce,
                mach = (float)vessel.mach,
                met_s = (float)vessel.missionTime,
                eva_active = vessel.isEVA,
                emotion = _currentEval.Emotion.ToString(),
                consciousness = _currentEval.Consciousness.ToString(),
                primary_cause = _currentEval.PrimaryCause,
                critical_timer_s = _criticalExposureTimer,
                lethal_limit_s = LethalExposureLimitSeconds,
                ingest_biometrics = _pushGForceToOrion,
                crew = crewDtos.ToArray()
            };

            return JsonUtility.ToJson(dto);
        }

        private void ProcessStateJson(string json)
        {
            try
            {
                HevStateDto parsed = JsonUtility.FromJson<HevStateDto>(json);
                if (parsed == null)
                {
                    _lastError = "Пустой JSON от /api/state";
                    _isConnected = false;
                    return;
                }

                _latestState = parsed;
                _isConnected = true;
                _lastError = string.Empty;

                _paramMap.Clear();
                if (parsed.parameters != null)
                {
                    foreach (HevParameterDto p in parsed.parameters)
                    {
                        if (!string.IsNullOrEmpty(p.id))
                            _paramMap[p.id] = p;
                    }
                }

                _currentEval = EvaluateCrewMetrics(parsed, _paramMap);
            }
            catch (Exception ex)
            {
                _isConnected = false;
                _lastError = "Ошибка парсинга JSON: " + ex.Message;
            }
        }

        private IEnumerator TriggerSimulatorScenario(string scenarioId)
        {
            string url = ApiBaseUrl.TrimEnd('/') + "/api/v1/simulator/" + scenarioId;
            using (UnityWebRequest req = new UnityWebRequest(url, "POST"))
            {
                req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes("{}"));
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                req.timeout = 3;
                yield return req.SendWebRequest();

                if (!req.isNetworkError && !req.isHttpError)
                {
                    ScreenMessages.PostScreenMessage(
                        "[ORION-MED] Сценарий активирован: " + scenarioId.ToUpper(),
                        3.0f,
                        ScreenMessageStyle.UPPER_RIGHT);
                }
            }
        }

        private IEnumerator SilenceAndAckAlertsCoroutine()
        {
            string baseUrl = ApiBaseUrl.TrimEnd('/');
            using (UnityWebRequest req = new UnityWebRequest(baseUrl + "/api/v1/alerts/silence-all", "POST"))
            {
                req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes("{}"));
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                req.timeout = 3;
                yield return req.SendWebRequest();
            }

            if (_latestState != null && _latestState.alerts != null)
            {
                foreach (HevAlertDto a in _latestState.alerts)
                {
                    if (a != null && !a.acknowledged && !string.IsNullOrEmpty(a.id))
                    {
                        using (UnityWebRequest ackReq = new UnityWebRequest(baseUrl + "/api/v1/alerts/" + a.id + "/ack", "POST"))
                        {
                            ackReq.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes("{}"));
                            ackReq.downloadHandler = new DownloadHandlerBuffer();
                            ackReq.SetRequestHeader("Content-Type", "application/json");
                            ackReq.timeout = 3;
                            yield return ackReq.SendWebRequest();
                        }
                    }
                }
            }

            ScreenMessages.PostScreenMessage(
                "<color=#44CCFF>[ORION-MED] Тревоги подтверждены (ACK / SILENCE)</color>",
                2.5f,
                ScreenMessageStyle.UPPER_RIGHT);
        }

        private CrewEvaluationResult EvaluateCrewMetrics(
            HevStateDto state,
            Dictionary<string, HevParameterDto> p)
        {
            var res = new CrewEvaluationResult();

            bool hrOk, hrvOk, spo2Ok, bpOk, dummy;
            float hr = GetVal(p, "heart_rate", 72f, out hrOk);
            float hrv = GetVal(p, "hrv", 55f, out hrvOk);
            float spo2 = GetVal(p, "spo2", 98f, out spo2Ok);
            float bpSys = GetVal(p, "bp_systolic", 118f, out bpOk);
            float temp = GetVal(p, "body_temp", 36.8f, out dummy);
            float co2 = GetVal(p, "cabin_co2", 2.0f, out dummy);
            float o2 = GetVal(p, "cabin_o2", 21.0f, out dummy);
            float press = GetVal(p, "cabin_pressure", 101.3f, out dummy);
            float doseRate = GetVal(p, "dose_rate", 18.0f, out dummy);
            float accDose = GetVal(p, "accumulated_dose", 1.6f, out dummy);
            float pvtRt = GetVal(p, "pvt_mean_rt", 265f, out dummy);
            float sleep = GetVal(p, "sleep_hours", 7.2f, out dummy);

            bool anySensorFault = p.Values.Any(x => x.status == "SENSOR_FAULT" || x.status == "STALE");
            bool solarFlareWarn =
                (state.space_weather_simulation != null && state.space_weather_simulation.space_weather_risk == "WARNING") ||
                (state.nasa_donki != null && state.nasa_donki.space_weather_risk == "WARNING");

            List<string> criticalReasons = new List<string>();

            if (spo2Ok && spo2 <= 88f)
                criticalReasons.Add(string.Format(CultureInfo.InvariantCulture, "Острая гипоксия (SpO2 {0:F1}%) -> KIT ECLSS-03", spo2));
            if (bpOk && (bpSys <= 85f || (bpSys <= 92f && hrOk && hr >= 128f)))
                criticalReasons.Add(string.Format(CultureInfo.InvariantCulture, "Геморрагический шок (АД {0:F0} мм рт.ст., ЧСС {1:F0}) -> KIT A-1", bpSys, hr));
            if (co2 >= 7.2f)
                criticalReasons.Add(string.Format(CultureInfo.InvariantCulture, "Токсическая гиперкапния (CO2 {0:F1} мм рт.ст.) -> KIT ECLSS-03", co2));
            if (o2 <= 17.0f || press <= 85.0f)
                criticalReasons.Add(string.Format(CultureInfo.InvariantCulture, "Декомпрессия / дефицит O2 ({0:F1} кПа, O2 {1:F1}%)", press, o2));
            if (hrOk && (hr >= 142f || hr <= 35f))
                criticalReasons.Add(string.Format(CultureInfo.InvariantCulture, "Критическая тахикардия (ЧСС {0:F0} уд/мин) -> CARDIO-KIT", hr));
            if (doseRate >= 750f || accDose >= 50f)
                criticalReasons.Add(string.Format(CultureInfo.InvariantCulture, "Острое радиационное поражение ({0:F0} мкГр/ч) -> STORM SHELTER", doseRate));
            if (temp >= 40.0f || temp <= 34.5f)
                criticalReasons.Add(string.Format(CultureInfo.InvariantCulture, "Термальный шок (T тела {0:F1}°C)", temp));

            if (criticalReasons.Count > 0)
            {
                res.Consciousness = KerbalConsciousness.Unconscious;
                res.IsLifeThreatening = true;
                res.PrimaryCause = string.Join("; ", criticalReasons.ToArray());
            }
            else if (pvtRt >= 430f || co2 >= 5.0f || sleep <= 4.0f || (hrvOk && hrv <= 15f && hr >= 120f))
            {
                res.Consciousness = KerbalConsciousness.CognitivelyImpaired;
                res.PrimaryCause = string.Format(
                    CultureInfo.InvariantCulture,
                    "Когнитивное снижение (PVT {0:F0} мс, CO2 {1:F1} мм рт.ст., HRV {2:F0} мс)",
                    pvtRt, co2, hrv);
            }
            else
            {
                res.Consciousness = KerbalConsciousness.Alert;
            }

            string medStatus = state.medical_status ?? "NOMINAL";
            bool masterWarning = state.master != null && state.master.warning;
            bool masterCaution = state.master != null && state.master.caution;

            if (res.IsLifeThreatening || masterWarning || medStatus == "WARNING" || solarFlareWarn)
            {
                res.Emotion = KerbalEmotion.Panic;
                res.WheeLevel = 0.0f;
                res.FearFactor = 1.0f;
                res.PanicLevel = 1.0f;
                if (!res.IsLifeThreatening)
                    res.PrimaryCause = GetTopAlertTitle(state) ?? "MASTER WARNING активен";
            }
            else if (masterCaution || medStatus == "CAUTION" || anySensorFault ||
                     (hrvOk && hrv <= 22f) || hr >= 110f || (bpOk && bpSys < 95f) || co2 >= 4.0f || doseRate >= 100f)
            {
                res.Emotion = KerbalEmotion.Stressed;
                res.WheeLevel = 0.0f;
                res.FearFactor = 0.65f;
                res.PanicLevel = 0.45f;
                if (res.Consciousness == KerbalConsciousness.Alert)
                    res.PrimaryCause = GetTopAlertTitle(state) ?? "Повышенный физиологический стресс (CAUTION)";
            }
            else if (medStatus == "NOMINAL" && hrOk && hr >= 55f && hr <= 88f &&
                     hrvOk && hrv >= 45f && spo2 >= 97f && co2 < 3.0f && pvtRt < 310f)
            {
                res.Emotion = KerbalEmotion.Joy;
                res.WheeLevel = 0.9f;
                res.FearFactor = 0.0f;
                res.PanicLevel = 0.0f;
                res.PrimaryCause = "Оптимальный тонус (все 4 контура R.I.D.G.E. в норме)";
            }
            else
            {
                res.Emotion = KerbalEmotion.Neutral;
                res.WheeLevel = 0.2f;
                res.FearFactor = 0.1f;
                res.PanicLevel = 0.0f;
                res.PrimaryCause = "Рабочее состояние (ADVISORY / NOMINAL)";
            }

            return res;
        }

        private static float GetVal(Dictionary<string, HevParameterDto> map, string key, float fallback, out bool isOk)
        {
            HevParameterDto p;
            if (map.TryGetValue(key, out p) && p != null && p.status == "OK")
            {
                isOk = true;
                return p.value;
            }
            isOk = false;
            return fallback;
        }

        private static string GetTopAlertTitle(HevStateDto state)
        {
            if (state.readiness != null && state.readiness.triage != null && !string.IsNullOrEmpty(state.readiness.triage.title))
            {
                string kit = !string.IsNullOrEmpty(state.readiness.triage.kit) && state.readiness.triage.kit != "NONE"
                    ? (" [" + state.readiness.triage.kit + "]")
                    : "";
                return state.readiness.triage.title + kit;
            }
            if (state.alerts != null && state.alerts.Length > 0)
            {
                HevAlertDto first = state.alerts[0];
                return first.title + " (" + first.severity + ")";
            }
            return null;
        }

        private void ApplyStateToActiveCrew(float dt)
        {
            List<ProtoCrewMember> crewList = vessel.GetVesselCrew();
            if (crewList == null || crewList.Count == 0)
                return;

            if (_currentEval.IsLifeThreatening)
                _criticalExposureTimer += dt;
            else
                _criticalExposureTimer = Mathf.Max(0f, _criticalExposureTimer - dt * 1.5f);

            if (_criticalExposureTimer >= LethalExposureLimitSeconds)
            {
                _criticalExposureTimer = 0f;
                ProtoCrewMember victim = crewList.FirstOrDefault(c => c != null && c.rosterStatus == ProtoCrewMember.RosterStatus.Assigned);
                if (victim != null)
                {
                    KillCrewMember(victim, _currentEval.PrimaryCause);
                    return;
                }
            }

            foreach (ProtoCrewMember crew in crewList)
            {
                if (crew == null) continue;

                ManageCognitiveRole(crew, _currentEval.Consciousness);

                if (_currentEval.Consciousness == KerbalConsciousness.Unconscious)
                {
                    if (!crew.inactive)
                    {
                        ScreenMessages.PostScreenMessage(
                            string.Format("<color=#FF4444>[ORION-MED] {0} потерял сознание: {1}!</color>", crew.name, _currentEval.PrimaryCause),
                            4.0f,
                            ScreenMessageStyle.UPPER_CENTER);
                    }
                    crew.SetInactive(5.0f, false);
                }

                ApplyFacialExpression(crew, _currentEval);
            }
        }

        private void ManageCognitiveRole(ProtoCrewMember crew, KerbalConsciousness state)
        {
            if (!_originalCrewTypes.ContainsKey(crew.name))
                _originalCrewTypes[crew.name] = crew.type;

            if (state == KerbalConsciousness.CognitivelyImpaired)
            {
                if (crew.type != ProtoCrewMember.KerbalType.Tourist)
                {
                    crew.type = ProtoCrewMember.KerbalType.Tourist;
                    ScreenMessages.PostScreenMessage(
                        string.Format("<color=#FFAA00>[ORION-MED] {0} дезориентирован ({1}) и временно не может управлять судном!</color>", crew.name, _currentEval.PrimaryCause),
                        4.0f,
                        ScreenMessageStyle.UPPER_CENTER);
                    vessel.CrewListSetDirty();
                }
            }
            else if (state == KerbalConsciousness.Alert)
            {
                ProtoCrewMember.KerbalType origType;
                if (_originalCrewTypes.TryGetValue(crew.name, out origType) && crew.type != origType)
                {
                    crew.type = origType;
                    ScreenMessages.PostScreenMessage(
                        string.Format("<color=#55FF55>[ORION-MED] {0} восстановил когнитивную работоспособность.</color>", crew.name),
                        3.0f,
                        ScreenMessageStyle.UPPER_CENTER);
                    vessel.CrewListSetDirty();
                }
            }
        }

        private static void ApplyFacialExpression(ProtoCrewMember crew, CrewEvaluationResult eval)
        {
            Kerbal kerbal = crew.KerbalRef;
            if (kerbal == null) return;

            if (eval.Emotion == KerbalEmotion.Panic)
                crew.isBadass = false;

            kerbalExpressionSystem expr = kerbal.GetComponent<kerbalExpressionSystem>();
            if (expr != null)
            {
                if (_fiFearFactor != null) _fiFearFactor.SetValue(expr, eval.FearFactor);
                if (_fiWheeLevel != null) _fiWheeLevel.SetValue(expr, eval.WheeLevel);
                if (_fiPanicLevel != null) _fiPanicLevel.SetValue(expr, eval.PanicLevel);
            }

            Animator anim = kerbal.GetComponentInChildren<Animator>();
            if (anim != null && anim.isInitialized)
            {
                TrySetAnimatorFloat(anim, "fear", eval.FearFactor);
                TrySetAnimatorFloat(anim, "whee", eval.WheeLevel);
                TrySetAnimatorFloat(anim, "panic", eval.PanicLevel);
            }
        }

        private static void TrySetAnimatorFloat(Animator anim, string paramName, float value)
        {
            foreach (AnimatorControllerParameter p in anim.parameters)
            {
                if (p.type == AnimatorControllerParameterType.Float &&
                    string.Equals(p.name, paramName, StringComparison.OrdinalIgnoreCase))
                {
                    anim.SetFloat(p.nameHash, value);
                    return;
                }
            }
        }

        private void KillCrewMember(ProtoCrewMember crew, string medicalReason)
        {
            string crewName = crew.name;
            Part seatPart = crew.seat != null
                ? crew.seat.part
                : vessel.parts.FirstOrDefault(p => p.protoModuleCrew.Contains(crew));

            ScreenMessages.PostScreenMessage(
                string.Format("<color=#FF2222><b>[ORION-MED // LETHAL OUTCOME]</b> Экипаж потерял {0}.\nПричина: {1}</color>", crewName, medicalReason),
                10.0f,
                ScreenMessageStyle.UPPER_CENTER);

            if (seatPart != null)
                seatPart.RemoveCrewmember(crew);

            crew.Die();

            if (crew.KerbalRef != null)
                crew.KerbalRef.die();

            vessel.CrewListSetDirty();
            GameEvents.onVesselCrewWasModified.Fire(vessel);
        }

        private void OnGUI()
        {
            if (!_showGui || !FlightGlobals.ready || vessel == null || !vessel.isActiveVessel)
                return;

            if (HighLogic.LoadedScene != GameScenes.FLIGHT)
                return;

            GUI.skin = HighLogic.Skin;
            _windowRect = GUILayout.Window(
                GetInstanceID() ^ 0x4F52494F,
                _windowRect,
                DrawOrionWindow,
                "R.I.D.G.E. // ORION-MED HEV-1 KSP BRIDGE [Alt+M]",
                GUILayout.Width(435f),
                GUILayout.MinHeight(560f));
        }

        private void DrawOrionWindow(int windowId)
        {
            GUILayout.BeginVertical();

            GUILayout.BeginHorizontal();
            string connText = _isConnected
                ? "<color=#00FF00>● LINK ONLINE (1 Hz SYNC)</color>"
                : string.Format("<color=#FF4444>● OFFLINE ({0})</color>", _lastError);
            GUILayout.Label("<b>Связь:</b> " + connText, GUILayout.Width(235f));
            ApiBaseUrl = GUILayout.TextField(ApiBaseUrl, GUILayout.ExpandWidth(true));
            GUILayout.EndHorizontal();

            if (!_isConnected || _latestState == null)
            {
                GUILayout.Space(8f);
                GUILayout.Label("Ожидание ответа от сервера ORION-MED (GET /api/state)...\nЗапустите run.bat в папке C:\\Users\\vasil\\OneDrive\\Desktop\\orion-med.");
                GUILayout.EndVertical();
                GUI.DragWindow();
                return;
            }

            // Верхний светофорный вердикт (Top Banner: MISSION STATUS + EVA CLEARANCE)
            string medColor = GetSeverityHex(_latestState.medical_status);
            string scenarioName = _latestState.mode != null ? _latestState.mode.scenario.ToUpper() : "NOMINAL";
            string evaStatus = (_latestState.readiness != null && _latestState.readiness.eva != null)
                ? _latestState.readiness.eva.status
                : "NO_BLOCKERS";
            int gatesClear = (_latestState.readiness != null && _latestState.readiness.eva != null)
                ? _latestState.readiness.eva.gates_clear
                : 4;
            int gatesTotal = (_latestState.readiness != null && _latestState.readiness.eva != null)
                ? _latestState.readiness.eva.gates_total
                : 4;
            bool evaGo = evaStatus == "NO_BLOCKERS";
            string evaText = evaGo
                ? string.Format("<color=#00FF00>GO ({0}/{1})</color>", gatesClear, gatesTotal)
                : string.Format("<color=#FF4444>NO-GO ({0}/{1})</color>", gatesClear, gatesTotal);

            GUILayout.Box(
                string.Format("<b>STATUS: <color={0}>{1}</color></b> ({2})  |  <b>EVA:</b> {3}", medColor, _latestState.medical_status, scenarioName, evaText),
                GUILayout.ExpandWidth(true));

            // R.I.D.G.E. Triage & Kit Banner
            if (_latestState.readiness != null && _latestState.readiness.triage != null)
            {
                string triageCol = GetSeverityHex(_latestState.readiness.triage.severity);
                string kitStr = (!string.IsNullOrEmpty(_latestState.readiness.triage.kit) && _latestState.readiness.triage.kit != "NONE")
                    ? (" | Набор: <b>" + _latestState.readiness.triage.kit + "</b>")
                    : "";
                GUILayout.Box(
                    string.Format("<color=#00C8FF><b>R.I.D.G.E.:</b></color> <color={0}>{1}</color>{2}", triageCol, _latestState.readiness.triage.title, kitStr),
                    GUILayout.ExpandWidth(true));
            }

            if (_currentEval.IsLifeThreatening)
            {
                float remain = Mathf.Max(0f, LethalExposureLimitSeconds - _criticalExposureTimer);
                GUI.color = Color.Lerp(Color.yellow, Color.red, Mathf.PingPong(Time.time * 4f, 1f));
                GUILayout.Box(
                    string.Format("<b>КРИТИЧЕСКАЯ УГРОЗА ЖИЗНИ ЭКИПАЖА!</b>\n{0}\nДо летального исхода: {1:F1} сек", _currentEval.PrimaryCause, remain),
                    GUILayout.ExpandWidth(true));
                GUI.color = Color.white;
            }

            GUILayout.Space(3f);
            GUILayout.Label("<b>Биометрия экипажа и среда кабины (ORION-MED HEV-1):</b>");
            GUILayout.BeginVertical("box");
            DrawMetricRow("Пульс (HR)", "heart_rate", "АД (BP Sys)", "bp_systolic");
            DrawMetricRow("Сатурация (SpO2)", "spo2", "Дыхание (RR)", "resp_rate");
            DrawMetricRow("Вариаб. (HRV)", "hrv", "Реакция (PVT)", "pvt_mean_rt");
            DrawMetricRow("CO2 кабины", "cabin_co2", "O2 кабины", "cabin_o2");
            DrawMetricRow("Давление", "cabin_pressure", "Мощн. дозы", "dose_rate");
            DrawMetricRow("Темп. тела", "body_temp", "Накопл. доза", "accumulated_dose");
            GUILayout.EndVertical();

            GUILayout.Space(3f);
            GUILayout.Label(string.Format("<b>Борт KSP: {0} (G: {1:F2}g | Выс: {2:F0} м):</b>", vessel.GetDisplayName(), vessel.geeForce, vessel.altitude));
            GUILayout.BeginVertical("box");
            _pushGForceToOrion = GUILayout.Toggle(_pushGForceToOrion, "Передавать перегрузки KSP (G-Force) в телеметрию ORION-MED");
            GUILayout.Label(string.Format("<b>Эмоция:</b> {0}   |   <b>Сознание:</b> {1}", _currentEval.Emotion, _currentEval.Consciousness));
            GUILayout.Label(string.Format("<b>Причина:</b> <i>{0}</i>", _currentEval.PrimaryCause));

            List<ProtoCrewMember> crewMembers = vessel.GetVesselCrew();
            if (crewMembers.Count == 0)
            {
                GUILayout.Label("<color=#AAAAAA>На борту нет кербалов (беспилотный режим)</color>");
            }
            else
            {
                foreach (ProtoCrewMember c in crewMembers)
                {
                    string stateBadge = c.inactive
                        ? "<color=#FF4444>[БЕЗ СОЗНАНИЯ]</color>"
                        : (c.type == ProtoCrewMember.KerbalType.Tourist
                            ? "<color=#FFAA00>[ДЕЗОРИЕНТИРОВАН / TOURIST]</color>"
                            : "<color=#00FF00>[В СТРОЮ]</color>");
                    GUILayout.Label(string.Format("• <b>{0}</b> ({1}) — {2}", c.name, c.trait, stateBadge));
                }
            }
            GUILayout.EndVertical();

            GUILayout.Space(3f);
            int alertCount = _latestState.alerts != null ? _latestState.alerts.Length : 0;
            GUILayout.BeginHorizontal();
            GUILayout.Label(string.Format("<b>Активные тревоги ({0}):</b>", alertCount));
            if (alertCount > 0 && GUILayout.Button("ACK / SILENCE ALL", GUILayout.Width(145f)))
            {
                StartCoroutine(SilenceAndAckAlertsCoroutine());
            }
            GUILayout.EndHorizontal();

            _alertsScrollPos = GUILayout.BeginScrollView(_alertsScrollPos, "box", GUILayout.Height(70f));
            if (alertCount == 0)
            {
                GUILayout.Label("<color=#88FF88>Активных тревог нет. Все контуры в зеленой зоне.</color>");
            }
            else
            {
                foreach (HevAlertDto a in _latestState.alerts)
                {
                    string col = GetSeverityHex(a.severity);
                    string proto = !string.IsNullOrEmpty(a.protocol_id) ? (" [" + a.protocol_id + "]") : "";
                    GUILayout.Label(string.Format("<color={0}>[{1}] <b>{2}</b>{3}</color>: {4}", col, a.severity, a.title, proto, a.message));
                }
            }
            GUILayout.EndScrollView();

            GUILayout.Space(3f);
            GUILayout.Label("<b>Симуляция аварий R.I.D.G.E. (синхронно с браузером):</b>");
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("HYPOXIA")) StartCoroutine(TriggerSimulatorScenario("hypoxia"));
            if (GUILayout.Button("HEMORRHAGE")) StartCoroutine(TriggerSimulatorScenario("hemorrhage"));
            if (GUILayout.Button("HIGH CO2")) StartCoroutine(TriggerSimulatorScenario("high_co2"));
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("TACHYCARDIA")) StartCoroutine(TriggerSimulatorScenario("tachycardia"));
            if (GUILayout.Button("SOLAR FLARE")) StartCoroutine(TriggerSimulatorScenario("solar_flare"));
            if (GUILayout.Button("SENSOR FAULT")) StartCoroutine(TriggerSimulatorScenario("sensor_failure"));
            GUILayout.EndHorizontal();
            if (GUILayout.Button("RECOVER TO NOMINAL (СТАБИЛИЗИРОВАТЬ МЕТРИКИ)"))
            {
                StartCoroutine(TriggerSimulatorScenario("nominal"));
            }

            GUILayout.EndVertical();
            GUI.DragWindow(new Rect(0, 0, 10000, 25));
        }

        private void DrawMetricRow(string labelLeft, string idLeft, string labelRight, string idRight)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(FormatParamCell(labelLeft, idLeft), GUILayout.Width(202f));
            GUILayout.Label(FormatParamCell(labelRight, idRight), GUILayout.Width(202f));
            GUILayout.EndHorizontal();
        }

        private string FormatParamCell(string label, string paramId)
        {
            HevParameterDto p;
            if (!_paramMap.TryGetValue(paramId, out p) || p == null)
                return label + ": <color=#888888>--</color>";

            if (p.status == "SENSOR_FAULT" || p.status == "STALE")
                return string.Format("{0}: <color=#FF8800><b>{1}</b></color>", label, p.status);

            string col = GetSeverityHex(p.band);
            return string.Format(CultureInfo.InvariantCulture, "{0}: <color={1}><b>{2:F1} {3}</b></color>", label, col, p.value, p.unit);
        }

        private static string GetSeverityHex(string severity)
        {
            switch (severity)
            {
                case "WARNING": return "#FF4444";
                case "CAUTION": return "#FFAA00";
                case "ADVISORY": return "#44CCFF";
                default: return "#00FF00";
            }
        }
    }

    #endregion
}
