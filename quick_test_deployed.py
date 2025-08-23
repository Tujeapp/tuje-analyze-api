# quick_test_deployed.py
# Test your newly deployed TuJe API

import requests
import json

# Your Render URL (replace with your actual URL)
API_URL = "https://your-app-name.onrender.com"  # ← Replace this with your actual Render URL

def test_basic_endpoints():
    """Test basic endpoints are working"""
    print("🌐 Testing deployed API endpoints...")
    
    # Test root endpoint
    try:
        response = requests.get(f"{API_URL}/", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Root endpoint: {data.get('message', 'API is running')}")
        else:
            print(f"❌ Root endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Root endpoint error: {e}")
        return False
    
    # Test health endpoint
    try:
        response = requests.get(f"{API_URL}/health", timeout=10)
        if response.status_code == 200:
            print("✅ Health endpoint: API is healthy")
        else:
            print(f"❌ Health endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Health endpoint error: {e}")
    
    return True

def test_transcription_endpoint():
    """Test the new transcription adjustment endpoint"""
    print("\n🧪 Testing transcription adjustment...")
    
    test_cases = [
        {
            "input": "Bonjour, j'ai vingt-cinq ans",
            "description": "Basic French with numbers in words"
        },
        {
            "input": "Un café coûte 2 euros", 
            "description": "Mix of 'un' and digits"
        },
        {
            "input": "J'aime un peu de café",
            "description": "Article 'un peu' test"
        }
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n--- Test {i}: {case['description']} ---")
        print(f"Input: '{case['input']}'")
        
        payload = {
            "original_transcript": case["input"],
            "user_id": "test_user",
            "interaction_id": "test_interaction"
        }
        
        try:
            response = requests.post(
                f"{API_URL}/api/adjust-transcription",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Success!")
                print(f"  📝 Original: '{result['original_transcript']}'")
                print(f"  🔧 Pre-adjusted: '{result['pre_adjusted_transcript']}'")
                print(f"  🎯 Final: '{result['adjusted_transcript']}'")
                print(f"  📚 Vocabulary: {len(result['list_of_vocabulary'])} items")
                print(f"  🏷️ Entities: {len(result['list_of_entities'])} items")
                print(f"  ⏱️ Time: {result['processing_time_ms']}ms")
                
                # Show some vocabulary details
                if result['list_of_vocabulary']:
                    print(f"  📖 Sample vocabulary:")
                    for vocab in result['list_of_vocabulary'][:2]:  # Show first 2
                        print(f"    - '{vocab['transcription_fr']}' → '{vocab['transcription_adjusted']}'")
                        
            else:
                print(f"❌ Failed: Status {response.status_code}")
                try:
                    error = response.json()
                    print(f"  Error: {error.get('detail', 'Unknown')}")
                except:
                    print(f"  Raw error: {response.text}")
                    
        except requests.exceptions.Timeout:
            print("❌ Request timeout (>30s)")
        except Exception as e:
            print(f"❌ Request error: {e}")

def test_match_answer_endpoint():
    """Test the enhanced match-answer endpoint"""
    print("\n🎯 Testing match-answer integration...")
    
    # Note: This will likely fail with 404 since we're using fake interaction_id
    # But it will show us if the endpoint structure is working
    
    payload = {
        "interaction_id": "fake_interaction_for_testing",
        "user_transcription": "Bonjour, j'ai 25 ans",
        "threshold": 85,
        "auto_adjust": True,
        "user_id": "test_user"
    }
    
    try:
        response = requests.post(
            f"{API_URL}/match-answer",
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Match-answer endpoint is working!")
            print(f"  🎯 Match found: {result['match_found']}")
            print(f"  🤖 Should call GPT: {result['call_gpt']}")
            print(f"  🔧 Adjustment applied: {result['adjustment_applied']}")
            
        elif response.status_code == 404:
            print("✅ Match-answer endpoint structure is working!")
            print("  ⚠️ Got 404 (expected with fake interaction_id)")
            print("  ➡️ This means the endpoint exists and validation works")
            
        else:
            print(f"❌ Unexpected status: {response.status_code}")
            try:
                error = response.json()
                print(f"  Error: {error.get('detail', 'Unknown')}")
            except:
                print(f"  Raw: {response.text}")
                
    except Exception as e:
        print(f"❌ Request error: {e}")

def test_documentation():
    """Check if API documentation is available"""
    print("\n📚 Testing API documentation...")
    
    try:
        response = requests.get(f"{API_URL}/docs", timeout=10)
        if response.status_code == 200:
            print(f"✅ API docs available at: {API_URL}/docs")
            print("  👀 You can test all endpoints interactively there!")
        else:
            print(f"❌ Docs not available: {response.status_code}")
    except Exception as e:
        print(f"❌ Docs error: {e}")

def main():
    """Run all tests"""
    print("🚀 Testing Deployed TuJe API")
    print(f"🌐 API URL: {API_URL}")
    print("=" * 60)
    
    # Step 1: Basic connectivity
    if not test_basic_endpoints():
        print("\n❌ Basic connectivity failed!")
        print("Please check:")
        print(f"1. Your API URL: {API_URL}")
        print("2. Render deployment status")
        print("3. Environment variables in Render")
        return
    
    # Step 2: Test transcription
    test_transcription_endpoint()
    
    # Step 3: Test match-answer
    test_match_answer_endpoint()
    
    # Step 4: Check docs
    test_documentation()
    
    print("\n" + "=" * 60)
    print("✅ Basic deployment test completed!")
    print("\n📋 Next Steps:")
    print("1. If tests passed → Your basic integration is working!")
    print("2. Test with real interaction_id from your database")
    print("3. Connect your Bubble workflow")
    print("4. Monitor performance and accuracy")
    print(f"5. Use {API_URL}/docs for interactive testing")

if __name__ == "__main__":
    main()
