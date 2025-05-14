import json
import os
import random
from flask import Flask, render_template, request, session, flash, redirect, url_for
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = os.urandom(24)

# 設定題目來源資料夾
QUESTIONS_DIR = "question"

# 定義八大次專科
CATEGORIES = [
    "心臟內科", "腸胃肝膽科", "胸腔內科", "腎臟科",
    "感染科", "風濕免疫過敏科", "血液腫瘤科", "內分泌暨新陳代謝科"
]

# 題目數量選項
NUM_QUESTIONS_OPTIONS = list(range(1, 11))

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        selected_category = request.form.get('category')
        num_questions_str = request.form.get('num_questions')

        if not selected_category or not num_questions_str:
            flash("請選擇科別和題數。", "error")
            return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)

        try:
            num_questions = int(num_questions_str)
        except ValueError:
            flash("題數選擇無效。", "error")
            return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)

        json_filename = os.path.join(QUESTIONS_DIR, f"{selected_category}.json")

        try:
            with open(json_filename, 'r', encoding='utf-8') as f:
                all_questions = json.load(f)
        except FileNotFoundError:
            flash(f"找不到科別 '{selected_category}' 的題目檔案。", "error")
            return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)
        except json.JSONDecodeError:
            flash(f"科別 '{selected_category}' 的題目檔案格式錯誤。", "error")
            return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)
        except Exception as e:
            flash(f"讀取題目時發生錯誤: {e}", "error")
            return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)

        if not all_questions:
            flash(f"科別 '{selected_category}' 沒有題目可供選擇。", "error")
            return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)

        if len(all_questions) < num_questions:
            selected_questions = all_questions
            if not selected_questions: 
                 flash(f"科別 '{selected_category}' 沒有題目可供選擇。", "error")
                 return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)
        else:
            selected_questions = random.sample(all_questions, num_questions)
        
        session['selected_question_ids'] = [q.get('id') for q in selected_questions if q.get('id')]
        session['current_category'] = selected_category
        # Clear previous analysis/generation when new questions are loaded
        session.pop('last_analysis_result', None)
        session.pop('learning_points_for_generation', None)
        session.pop('analyzed_question_ids', None)
        session.pop('last_generated_question', None)

        return redirect(url_for('show_quiz_results')) # Redirect to the new GET route
    
    # GET request: Clear session for a fresh start
    session.pop('gemini_api_key', None)
    session.pop('gemini_api_key_valid', None)
    session.pop('selected_question_ids', None)
    session.pop('current_category', None)
    session.pop('last_analysis_result', None)
    session.pop('learning_points_for_generation', None)
    session.pop('analyzed_question_ids', None)
    session.pop('last_generated_question', None)
    # flash("已清除之前的狀態，請重新開始。", "info") # Optional: inform user

    return render_template('index_quiz.html', categories=CATEGORIES, num_options=NUM_QUESTIONS_OPTIONS)

@app.route('/show_quiz_results', methods=['GET'])
def show_quiz_results():
    if 'selected_question_ids' not in session or 'current_category' not in session:
        flash("沒有可顯示的題目，請先選擇科別和題數。", "warning")
        return redirect(url_for('index'))

    category = session['current_category']
    s_q_ids = session['selected_question_ids']
    json_filename = os.path.join(QUESTIONS_DIR, f"{category}.json")

    try:
        with open(json_filename, 'r', encoding='utf-8') as f:
            all_category_questions = json.load(f)
    except FileNotFoundError:
        flash(f"找不到科別 '{category}' 的題目檔案 ({json_filename})。", "error")
        return redirect(url_for('index'))
    except json.JSONDecodeError:
        flash(f"科別 '{category}' 的題目檔案 ({json_filename}) 格式錯誤。", "error")
        return redirect(url_for('index'))
    except Exception as e:
        flash(f"讀取題目檔案 '{json_filename}' 時發生錯誤: {e}", "error")
        return redirect(url_for('index'))

    # Filter to get the actual current questions and preserve order from s_q_ids
    questions_map = {q.get('id'): q for q in all_category_questions}
    ordered_current_questions = [questions_map[id_] for id_ in s_q_ids if id_ in questions_map]

    if not ordered_current_questions and s_q_ids: # Some IDs were not found
        flash(f"部分選定題目ID在 '{category}.json' 中找不到，可能檔案已變更。", "warning")
    elif not ordered_current_questions:
        flash(f"科別 '{category}' 中沒有與所選ID匹配的題目。", "info")
        # It's possible selected_question_ids was empty, though index route should prevent this for valid selections
        return redirect(url_for('index'))

    display_questions = []
    for q_data in ordered_current_questions:
        options_text = []
        if isinstance(q_data.get('options'), dict):
            for key, value in sorted(q_data['options'].items()): 
                options_text.append(f"{key}: {value}")
        display_questions.append({
            "id": q_data.get("id", "N/A"),
            "answer": q_data.get("answer", "N/A"),
            "stem": q_data.get("stem", "N/A"),
            "options_display": "\n".join(options_text)
        })

    analysis_result = session.get('last_analysis_result')
    generated_question = session.get('last_generated_question')

    return render_template('results_quiz.html', 
                           questions=display_questions, 
                           category=session['current_category'], 
                           num_selected=len(ordered_current_questions),
                           gemini_api_key=session.get('gemini_api_key'),
                           analysis_result=analysis_result,
                           generated_question=generated_question
                           )

@app.route('/validate_api_key', methods=['POST'])
def validate_api_key():
    api_key = request.form.get('api_key')
    if api_key:
        session['gemini_api_key'] = api_key
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash-8b')
            model.generate_content("Hello") 
            session['gemini_api_key_valid'] = True
            flash("Gemini API 金鑰已成功驗證並儲存。", "success")
        except Exception as e:
            session['gemini_api_key_valid'] = False
            flash(f"Gemini API 金鑰驗證失敗: {e}", "error")
    else:
        session.pop('gemini_api_key', None)
        session.pop('gemini_api_key_valid', None)
        flash("API 金鑰已清除。", "info")
    
    return redirect(url_for('show_quiz_results')) # Redirect to show_quiz_results

@app.route('/analyze_learning_points', methods=['POST'])
def analyze_learning_points():
    if not session.get('gemini_api_key_valid'):
        flash("請先設定並驗證有效的 Gemini API 金鑰。", "error")
        return redirect(url_for('index')) # Or back to results if preferred, with current context

    selected_ids = request.form.getlist('selected_question_ids')
    if not selected_ids:
        flash("請至少選擇一題進行考點分析。", "error")
        # Redirect back to results page, show_quiz_results will use session data to display.
        return redirect(url_for('show_quiz_results'))

    questions_to_analyze = []
    if 'current_category' in session:
        category = session['current_category']
        json_filename = os.path.join(QUESTIONS_DIR, f"{category}.json")
        try:
            with open(json_filename, 'r', encoding='utf-8') as f:
                all_category_questions = json.load(f)
            
            # Filter questions based on selected_ids from the form
            questions_map = {q.get('id'): q for q in all_category_questions}
            questions_to_analyze = [questions_map[id_] for id_ in selected_ids if id_ in questions_map]

        except FileNotFoundError:
            flash(f"分析時找不到科別 '{category}' 的題目檔案。", "error")
            return redirect(url_for('show_quiz_results'))
        except json.JSONDecodeError:
            flash(f"分析時科別 '{category}' 的題目檔案格式錯誤。", "error")
            return redirect(url_for('show_quiz_results'))
        except Exception as e:
            flash(f"分析時讀取題目檔案發生錯誤: {e}", "error")
            return redirect(url_for('show_quiz_results'))
    else:
        flash("未設定目前科別，無法載入題目進行分析。", "error")
        return redirect(url_for('index'))

    if not questions_to_analyze:
        flash("找不到選中的題目資訊 (可能ID不存在或檔案讀取問題)，請重試。", "error")
        # Consider if redirect to index or show_quiz_results is better
        return redirect(url_for('show_quiz_results'))

    analysis_results_text = "### 考點分析結果:\n\n"
    learning_points_for_generation = [] # For the next step

    try:
        genai.configure(api_key=session.get('gemini_api_key'))
        model = genai.GenerativeModel('gemini-2.0-flash') 

        system_prompt = """你是一位醫學教育專家。請分析此題目，並根據提供的答案撰寫詳解，並扼要地列出其核心考點。"""

        for q_to_analyze in questions_to_analyze:
            question_text = f"題目ID: {q_to_analyze.get('id')}\n"
            question_text += f"題幹: {q_to_analyze.get('stem')}\n"
            question_text += "選項:\n"
            options = q_to_analyze.get('options', {})
            for opt_key, opt_val in sorted(options.items()):
                question_text += f"{opt_key}: {opt_val}\n"
            question_text += f"正確答案: {q_to_analyze.get('answer')}\n"
            
            prompt_for_analysis = f"{system_prompt}\n\n以下是題目內容：\n{question_text}\n\n請分析此題的核心考點並解釋答案："
            
            response = model.generate_content(prompt_for_analysis)
            points = response.text.strip()
            analysis_results_text += f"**題目 ID: {q_to_analyze.get('id')}**\n考點:\n{points}\n\n---\n"
            learning_points_for_generation.append(points) # Store raw points for next step

        session['last_analysis_result'] = analysis_results_text
        session['learning_points_for_generation'] = "\n".join(learning_points_for_generation)
        session['analyzed_question_ids'] = selected_ids # Store IDs of analyzed questions
        session.pop('last_generated_question', None) # Clear previous generated question
        flash("考點分析完成。", "success")

    except Exception as e:
        flash(f"考點分析過程中發生錯誤: {e}", "error")
        session['last_analysis_result'] = "分析失敗，請檢查 API 金鑰或稍後重試。"
        session.pop('learning_points_for_generation', None)

    # Re-render results page with analysis
    display_questions = []
    if 'current_questions' in session:
        for q_data in session['current_questions']:
            options_text = []
            if isinstance(q_data.get('options'), dict):
                for key, value in sorted(q_data['options'].items()): 
                    options_text.append(f"{key}: {value}")
            display_questions.append({
                "id": q_data.get("id", "N/A"),
                "answer": q_data.get("answer", "N/A"),
                "stem": q_data.get("stem", "N/A"),
                "options_display": "\n".join(options_text)
            })
            
    return redirect(url_for('show_quiz_results')) # Redirect

@app.route('/generate_similar_questions', methods=['POST'])
def generate_similar_questions():
    if not session.get('gemini_api_key_valid'):
        flash("請先設定並驗證有效的 Gemini API 金鑰才能生成題目。", "error")
        return redirect(url_for('show_quiz_results'))

    print("DEBUG: Entered generate_similar_questions route") # DEBUG line

    learning_points = session.pop('learning_points_for_generation', None)
    analyzed_ids = session.pop('analyzed_question_ids', [])

    print(f"DEBUG: Popped learning_points: {learning_points is not None}") # DEBUG line
    print(f"DEBUG: Popped analyzed_ids: {analyzed_ids}") # DEBUG line

    if not learning_points:
        flash("請先進行考點分析，才能生成類似題目。", "error")
        print("DEBUG: No learning points, redirecting.") # DEBUG line
        return redirect(url_for('show_quiz_results'))

    generated_question_data = None
    try:
        genai.configure(api_key=session.get('gemini_api_key'))
        model = genai.GenerativeModel('gemini-2.0-flash')

        system_prompt_generation = """你是一位醫學命題專家。基於以下提供的考點和原始題目，請設計一道全新的單選選擇題。新題目的題幹和選項都必須與原始題目不同，但要圍繞相似的醫學考點。題目有四個選項（A, B, C, D），並且提供答案。新題目的難度應該略高於原本題目。請確保題幹清晰，選項只有一個是最佳答案。你的輸出格式應該遵循以下格式：
題幹：[新題目的題幹]
選項A：
選項B：
選項C：
選項D：
正確答案：[A/B/C/D]
"""
        
        original_questions_text = "### 參考的原始題目資訊如下：\n"
        print(f"DEBUG: Initial original_questions_text: {original_questions_text[:50]}...") # DEBUG line
        
        if 'current_category' in session and analyzed_ids:
            category = session['current_category']
            json_filename = os.path.join(QUESTIONS_DIR, f"{category}.json")
            print(f"DEBUG: Attempting to load original questions from: {json_filename}") # DEBUG line
            try:
                with open(json_filename, 'r', encoding='utf-8') as f:
                    all_category_questions = json.load(f)
                
                questions_map = {q.get('id'): q for q in all_category_questions}
                found_any_original = False
                for q_id in analyzed_ids:
                    q_data = questions_map.get(q_id)
                    if q_data:
                        found_any_original = True
                        original_questions_text += f"\n--- 原始題目 ID: {q_data.get('id')} ---\n"
                        original_questions_text += f"題幹: {q_data.get('stem')}\n"
                        original_questions_text += "選項:\n"
                        options = q_data.get('options', {})
                        for opt_key, opt_val in sorted(options.items()):
                            original_questions_text += f"{opt_key}: {opt_val}\n"
                        original_questions_text += f"正確答案: {q_data.get('answer')}\n"
                if not found_any_original:
                     original_questions_text += "(未能從檔案中找到已分析的原始題目資訊)\n"
                print(f"DEBUG: Constructed original_questions_text length: {len(original_questions_text)}") # DEBUG line
            except Exception as e:
                original_questions_text += f"(讀取原始題目時發生錯誤: {e})\n"
                print(f"DEBUG: Error loading original questions: {e}") # DEBUG line
        else:
            if not analyzed_ids:
                original_questions_text += "(無已分析的題目ID可供參考)\n"
            else: # current_category missing
                original_questions_text += "(目前科別未設定，無法載入原始題目參考)\n"
            print(f"DEBUG: original_questions_text (no file load branch): {original_questions_text[:100]}...") # DEBUG line


        prompt_for_generation = f"{system_prompt_generation}\n\n{original_questions_text}\n\n參考考點如下：\n{learning_points}\n\n請嚴格依照上述要求，特別是題幹和選項的新穎性，根據考點出題："
        print(f"DEBUG: Final prompt_for_generation (first 200 chars): {prompt_for_generation[:200]}...") # DEBUG line
        # It might be too long to print the whole prompt if it's very large.
        # Consider writing to a temp file if needed:
        # with open("debug_prompt.txt", "w", encoding="utf-8") as f_debug:
        # f_debug.write(prompt_for_generation)
        # print("DEBUG: Full prompt written to debug_prompt.txt")

        print("DEBUG: About to call model.generate_content()") # DEBUG line
        response = model.generate_content(prompt_for_generation)
        print("DEBUG: model.generate_content() returned") # DEBUG line
        
        generated_text = response.text.strip()
        print(f"DEBUG: Generated text (first 100 chars): {generated_text[:100]}...") # DEBUG line
        
        # 解析生成的文本
        parsed_q = parse_generated_question(generated_text)
        if parsed_q:
            options_display_list = []
            if isinstance(parsed_q.get('options'), dict):
                for key, value in sorted(parsed_q['options'].items()):
                    options_display_list.append(f"{key}: {value}")
            
            generated_question_data = {
                "stem": parsed_q.get("stem", "未能解析題幹"),
                "options_display": "\n".join(options_display_list),
                "answer": parsed_q.get("answer", "未能解析答案")
            }
            session['last_generated_question'] = generated_question_data
            flash("已成功生成類似題目。", "success")
        else:
            flash("無法從模型回應中解析出完整的題目結構，請重試。", "warning")
            session['last_generated_question'] = {"stem": generated_text, "options_display": "", "answer": "解析失敗"} # Show raw output if parse fails

    except Exception as e:
        flash(f"生成類似題目過程中發生錯誤: {e}", "error")
        session.pop('last_generated_question', None)

    return redirect(url_for('show_quiz_results')) # Redirect

def parse_generated_question(text):
    """解析模型生成的題目文本"""
    lines = text.split('\n')
    data = {}
    options = {}
    # Expected keys mapping to how they appear in the text after the colon
    key_map = {
        "題幹：": "stem",
        "選項A：": "A",
        "選項B：": "B",
        "選項C：": "C",
        "選項D：": "D",
        "正確答案：": "answer"
    }
    current_option_key = None

    for line in lines:
        found_key = False
        for prefix, field_name in key_map.items():
            if line.startswith(prefix):
                value = line[len(prefix):].strip()
                if field_name in ["A", "B", "C", "D"]:
                    options[field_name] = value
                else:
                    data[field_name] = value
                found_key = True
                break
        # This part is removed as multi-line options are not explicitly handled by this simple parser
        # if not found_key and current_option_key and current_option_key in options:
        #    options[current_option_key] += "\n" + line.strip()
            
    if options:
        data['options'] = options
    
    # Basic validation: Check if essential parts are present
    if "stem" in data and "options" in data and len(data["options"]) == 4 and "answer" in data:
        return data
    return None

if __name__ == '__main__':
    if not os.path.exists('templates'):
        os.makedirs('templates')
    app.run(debug=True) 